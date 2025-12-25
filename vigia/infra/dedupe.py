import os
import hashlib
from datetime import datetime, timezone

from ..core.config import _parse_int, get_kusto_db_name
from ..core.kql import _escape_kql_string
from ..core.timeutil import _round_float, _to_iso_datetime
from .clients import get_kusto_client


# ---------- Deterministic EventId / Dedupe / Gate ----------

def _compute_event_id(payload: dict) -> str:
    dec = _parse_int(os.environ.get("DEDUP_LATLON_DECIMALS", "3"), 3, 1, 6)
    bucket_min = _parse_int(os.environ.get("DEDUP_TIME_BUCKET_MINUTES", "60"), 60, 1, 1440)

    lat = _round_float(payload.get("Latitude"), dec)
    lon = _round_float(payload.get("Longitude"), dec)
    hz = (payload.get("HazardType") or "none").strip().lower()

    ts_iso = _to_iso_datetime(payload.get("Timestamp"))
    dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    minute = (dt.minute // bucket_min) * bucket_min
    bucketed = dt.replace(minute=minute, second=0, microsecond=0)
    time_bucket = bucketed.astimezone(timezone.utc).isoformat()

    evidence = (payload.get("GaussianSplatURL") or "") + "|" + (payload.get("ReportId") or "")
    evidence_hash = hashlib.sha256(evidence.encode("utf-8")).hexdigest()

    raw = f"{lat}|{lon}|{time_bucket}|{hz}|{evidence_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _kql_dedupe_summary(payload: dict):
    db = get_kusto_db_name()
    dec = _parse_int(os.environ.get("DEDUP_LATLON_DECIMALS", "3"), 3, 1, 6)
    bucket_min = _parse_int(os.environ.get("DEDUP_TIME_BUCKET_MINUTES", "60"), 60, 1, 1440)

    lat = _round_float(payload.get("Latitude"), dec)
    lon = _round_float(payload.get("Longitude"), dec)
    hz = _escape_kql_string((payload.get("HazardType") or "none"))
    ts_iso = _to_iso_datetime(payload.get("Timestamp"))

    ttl_hours = _parse_int(os.environ.get("AUDIT_IDEMPOTENCY_TTL_HOURS", "24"), 24, 1, 168)

    q = f"""
    RoadTelemetry
    | where Timestamp > ago({ttl_hours}h)
    | extend LatB = round(Latitude, {dec}), LonB = round(Longitude, {dec}), TimeB = bin(Timestamp, {bucket_min}m)
    | where HazardType == '{hz}'
    | where LatB == {lat} and LonB == {lon}
    | where TimeB == bin(datetime({ts_iso}), {bucket_min}m)
    | summarize DuplicateCount = count(), SampleReportIds = make_set(ReportId, 20) by HazardType, LatB, LonB, TimeB
    """
    table = get_kusto_client().execute(db, q).primary_results[0]
    if not table.rows:
        group_key = f"{hz}|{lat}|{lon}|{ts_iso}"
        gid = hashlib.sha256(group_key.encode("utf-8")).hexdigest()
        return {"duplicate_count": 0, "duplicate_group_id": gid, "sample_report_ids": []}

    cols = [c.column_name for c in table.columns]
    row = dict(zip(cols, table.rows[0]))
    group_key = f"{row.get('HazardType')}|{row.get('LatB')}|{row.get('LonB')}|{row.get('TimeB')}"
    gid = hashlib.sha256(str(group_key).encode("utf-8")).hexdigest()

    return {
        "duplicate_count": int(row.get("DuplicateCount") or 0),
        "duplicate_group_id": gid,
        "sample_report_ids": row.get("SampleReportIds") or [],
    }