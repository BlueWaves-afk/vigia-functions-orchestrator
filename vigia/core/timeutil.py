from datetime import datetime, timezone


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _to_iso_datetime(val):
    """
    Accepts:
      - ISO-8601 string
      - epoch ms/int/float
      - missing -> now
    Returns ISO-8601 string.
    """
    if val is None or val == "":
        return _utc_now_iso()

    # epoch millis
    if isinstance(val, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(val) / 1000.0, tz=timezone.utc)
            return dt.isoformat()
        except Exception:
            return _utc_now_iso()

    # string
    if isinstance(val, str):
        s = val.strip()
        # epoch string?
        if s.isdigit():
            try:
                dt = datetime.fromtimestamp(float(s) / 1000.0, tz=timezone.utc)
                return dt.isoformat()
            except Exception:
                return _utc_now_iso()
        # ISO-ish
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return _utc_now_iso()

    return _utc_now_iso()


def _round_float(x, d):
    try:
        return round(float(x), d)
    except Exception:
        return None