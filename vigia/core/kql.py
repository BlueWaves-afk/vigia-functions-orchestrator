def _escape_kql_string(s: str) -> str:
    return (s or "").replace("'", "''")