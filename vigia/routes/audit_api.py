import logging
import azure.functions as func

from vigia.core.jsonx import json_response
from vigia.core.kql import _escape_kql_string
from vigia.core.config import _parse_int, get_kusto_db_name, get_audit_table_name
from vigia.infra.clients import get_kusto_client
from vigia.infra.audit_store import _audit_get_latest

bp = func.Blueprint()


@bp.route(route="audit-latest", methods=["GET"])
def audit_latest(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /audit-latest?event_id=...
    """
    try:
        event_id = (req.params.get("event_id") or "").strip()
        if not event_id:
            return json_response({"error": "Missing event_id"}, 400)

        latest = _audit_get_latest(event_id)
        return json_response({"found": bool(latest), "event_id": event_id, "latest": latest}, 200)

    except Exception as e:
        logging.error("audit-latest error", exc_info=True)
        return json_response({"error": str(e)}, 500)


@bp.route(route="audit-history", methods=["GET"])
def audit_history(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /audit-history?event_id=...&limit=50
    """
    try:
        db = get_kusto_db_name()
        audit_table = get_audit_table_name()

        event_id = (req.params.get("event_id") or "").strip()
        if not event_id:
            return json_response({"error": "Missing event_id"}, 400)

        limit = _parse_int(req.params.get("limit", "50"), 50, 1, 200)
        eid = _escape_kql_string(event_id)

        q = f"""
            {audit_table}
            | where EventId == '{eid}'
            | extend VerificationReasoning = column_ifexists('VerificationReasoning', tostring(Details.verification_reasoning))
            | sort by UpdatedAt asc
            | take {limit}
            """
        table = get_kusto_client().execute(db, q).primary_results[0]
        cols = [c.column_name for c in table.columns]
        rows = [dict(zip(cols, r)) for r in table.rows]

        return json_response({"event_id": event_id, "count": len(rows), "rows": rows}, 200)

    except Exception as e:
        logging.error("audit-history error", exc_info=True)
        return json_response({"error": str(e)}, 500)


@bp.route(route="audit-explain", methods=["GET"])
def audit_explain(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /audit-explain?event_id=...
    Compact explanation for copilot.
    """
    try:
        db = get_kusto_db_name()
        audit_table = get_audit_table_name()

        event_id = (req.params.get("event_id") or "").strip()
        if not event_id:
            return json_response({"error": "Missing event_id"}, 400)

        eid = _escape_kql_string(event_id)

        q = f"""
            {audit_table}
            | where EventId == '{eid}'
            | extend VerificationReasoning = column_ifexists('VerificationReasoning', tostring(Details.verification_reasoning))
            | sort by UpdatedAt asc
            """
        table = get_kusto_client().execute(db, q).primary_results[0]
        cols = [c.column_name for c in table.columns]
        rows = [dict(zip(cols, r)) for r in table.rows]

        if not rows:
            return json_response({"found": False, "event_id": event_id}, 200)

        latest = rows[-1]
        explanation = {
            "event_id": event_id,
            "latest_status": latest.get("Status"),
            "updated_at": str(latest.get("UpdatedAt")),
            "verification_reasoning": latest.get("VerificationReasoning"),
            "timeline": [
                {
                    "status": r.get("Status"),
                    "updated_at": str(r.get("UpdatedAt")),
                    "agent": r.get("Agent"),
                    "reasoning": r.get("VerificationReasoning"),
                }
                for r in rows
            ],
        }
        return json_response(explanation, 200)

    except Exception as e:
        logging.error("audit-explain error", exc_info=True)
        return json_response({"error": str(e)}, 500)