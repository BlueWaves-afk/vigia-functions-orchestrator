import json

from ..core.config import get_audit_table_name, get_kusto_db_name
from ..core.jsonx import _json_fallback
from ..core.kql import _escape_kql_string
from ..core.timeutil import _round_float, _to_iso_datetime
from .clients import _CLIENTS, _LOCK, get_kusto_client


# ---------- Audit / Idempotency ----------

def _audit_has_verification_reasoning_col() -> bool:
    """
    Cache whether AuditEvents has VerificationReasoning.
    Safe fallback if user hasn't altered the table yet.
    """
    cache_key = "audit_has_verification_reasoning"
    if cache_key in _CLIENTS:
        return _CLIENTS[cache_key]

    db = get_kusto_db_name()
    audit_table = get_audit_table_name()

    try:
        # control command: schema info
        cmd = f".show table {audit_table} schema"
        table = get_kusto_client().execute_mgmt(db, cmd).primary_results[0]
        cols = [c.column_name for c in table.columns]
        # result includes a column that contains schema text; search within rows
        joined = " ".join([str(x) for r in table.rows for x in r])
        has_col = ("VerificationReasoning" in joined)
    except Exception:
        has_col = False

    with _LOCK:
        _CLIENTS[cache_key] = has_col
    return has_col


def _audit_append(event_id: str, report_id: str, status: str, details: dict, verification_reasoning: str = ""):
    """
    Append-only audit log row into AuditEvents (or AUDIT_TABLE_NAME).
    Must match FULL table schema (incl. VerificationReasoning).
    """
    db = get_kusto_db_name()
    audit_table = get_audit_table_name()

    # Pull base telemetry fields from details["payload"] if present
    p = (details or {}).get("payload") or {}
    device_id = str(p.get("DeviceId") or p.get("deviceId") or "")
    ts_iso = _to_iso_datetime(p.get("Timestamp"))
    lat = _round_float(p.get("Latitude"), 6) or 0.0
    lon = _round_float(p.get("Longitude"), 6) or 0.0
    hazard_type = (p.get("HazardType") or "none")

    # Optional metadata (agent triggers / ledger writes)
    agent = str((details or {}).get("agent") or "")
    run_id = str((details or {}).get("run_id") or (details or {}).get("RunId") or "")
    ledger_tx = str((details or {}).get("transactionId") or (details or {}).get("LedgerTxId") or "")

    # Receipt + Details
    receipt_obj = (details or {}).get("receipt_result") or (details or {}).get("Receipt") or {}
    details_obj = details or {}

    # ✅ allow caller override via keyword arg
    if verification_reasoning:
        details_obj["verification_reasoning"] = verification_reasoning

    # NEW: reasoning column (string) (your original logic, unchanged)
    verification_reasoning = str(
        verification_reasoning
        or (details_obj or {}).get("VerificationReasoning")
        or (details_obj or {}).get("verification_reasoning")
        or (details_obj or {}).get("reasoning")
        or ""
    )

    def esc(s: str) -> str:
        return _escape_kql_string(s)

    eid = esc(event_id)
    rid = esc(report_id or "")
    did = esc(device_id)
    hz = esc(str(hazard_type))
    st = esc(status or "")
    ag = esc(agent)
    rn = esc(run_id)
    ltx = esc(ledger_tx)
    vr = esc(verification_reasoning)

    details_json = esc(json.dumps(details_obj, ensure_ascii=False, default=_json_fallback))
    receipt_json = esc(json.dumps(receipt_obj or {}, ensure_ascii=False, default=_json_fallback))
    mgmt = f""".append {audit_table} <|
            print
                EventId='{eid}',
                ReportId='{rid}',
                DeviceId='{did}',
                Timestamp=datetime('{esc(ts_iso)}'),
                Latitude=real({lat}),
                Longitude=real({lon}),
                HazardType='{hz}',
                Status='{st}',
                UpdatedAt=now(),
                Agent='{ag}',
                RunId='{rn}',
                LedgerTxId='{ltx}',
                Receipt=parse_json('{receipt_json}'),
                Details=parse_json('{details_json}'),
                CreatedAt=now(),
                VerificationReasoning='{vr}'
            | project EventId, ReportId, DeviceId, Timestamp, Latitude, Longitude, HazardType, Status, UpdatedAt, Agent, RunId, LedgerTxId, Receipt, Details, CreatedAt, VerificationReasoning
            """
    get_kusto_client().execute_mgmt(db, mgmt)


def _audit_get_latest(event_id: str):
    db = get_kusto_db_name()
    audit_table = get_audit_table_name()
    eid = _escape_kql_string(event_id)

    q = f"""
        {audit_table}
        | where EventId == '{eid}'
        | extend VerificationReasoning = column_ifexists('VerificationReasoning', tostring(Details.verification_reasoning))
        | top 1 by UpdatedAt desc
        | project Status, UpdatedAt, Details, VerificationReasoning
        """
    res = get_kusto_client().execute(db, q).primary_results[0]
    if not res.rows:
        return None
    cols = [c.column_name for c in res.columns]
    row = dict(zip(cols, res.rows[0]))
    return row