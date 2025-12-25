import os


def require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing environment variable: {name}")
    return val


def _parse_int(value, default, min_v=None, max_v=None):
    try:
        iv = int(value)
    except Exception:
        iv = int(default)
    if min_v is not None:
        iv = max(min_v, iv)
    if max_v is not None:
        iv = min(max_v, iv)
    return iv


def _parse_float(value, name):
    try:
        return float(value)
    except Exception:
        raise ValueError(f"Invalid float for '{name}': {value}")


def get_kusto_db_name() -> str:
    return os.environ.get("FABRIC_DB_NAME") or os.environ.get("FABRIC_KUSTO_DB") or "VigiaRoadDB"


def get_audit_table_name() -> str:
    return os.environ.get("AUDIT_TABLE_NAME") or "AuditEvents"