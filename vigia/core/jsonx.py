import json
from datetime import datetime

import azure.functions as func


def _json_fallback(o):
    # datetimes
    if isinstance(o, datetime):
        return o.isoformat()

    # common SDK patterns
    for m in ("as_dict", "to_dict", "dict"):
        if hasattr(o, m) and callable(getattr(o, m)):
            try:
                return getattr(o, m)()
            except Exception:
                pass

    # last resort
    try:
        return str(o)
    except Exception:
        return "<non-serializable>"


def _json_default(o):
    # Kusto rows often contain python datetime objects -> json.dumps can't serialize them
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)  # safe fallback (e.g., Decimal, etc.)


def json_response(payload, status_code=200):
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False, default=_json_default),
        status_code=status_code,
        mimetype="application/json",
    )