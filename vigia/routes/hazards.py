import logging
import azure.functions as func

from vigia.core.jsonx import json_response
from vigia.core.kql import _escape_kql_string
from vigia.core.config import _parse_int, _parse_float, get_kusto_db_name
from vigia.infra.clients import get_kusto_client

bp = func.Blueprint()


@bp.route(route="query-hazards", methods=["GET"])
def query_road_hazards(req: func.HttpRequest) -> func.HttpResponse:
    try:
        db = get_kusto_db_name()
        hazard_type = _escape_kql_string(req.params.get("hazard_type", "Pothole"))
        hours = _parse_int(req.params.get("time_range_hours", "24"), default=24, min_v=1, max_v=168)

        query = (
            "RoadTelemetry "
            f"| where HazardType == '{hazard_type}' "
            f"| where Timestamp > ago({hours}h) "
            "| summarize Count = count() by Latitude, Longitude "
            "| top 5 by Count"
        )

        table = get_kusto_client().execute(db, query).primary_results[0]
        cols = [c.column_name for c in table.columns]
        data = [dict(zip(cols, row)) for row in table.rows]
        return json_response(data, 200)

    except ValueError as ve:
        return json_response({"error": str(ve)}, 400)
    except Exception as e:
        logging.error("KQL Error", exc_info=True)
        return json_response({"error": str(e)}, 500)


@bp.route(route="get-regional-hazards", methods=["POST"])
def get_regional_hazards(req: func.HttpRequest) -> func.HttpResponse:
    try:
        db = get_kusto_db_name()
        body = req.get_json()

        n = _parse_float(body.get("n"), "n")
        s = _parse_float(body.get("s"), "s")
        e = _parse_float(body.get("e"), "e")
        w = _parse_float(body.get("w"), "w")

        if s > n or w > e:
            return json_response({"error": "Invalid bounds: require s<=n and w<=e"}, 400)

        query = (
            "RoadTelemetry "
            f"| where Latitude between({s} .. {n}) "
            f"| where Longitude between({w} .. {e}) "
            "| where ConfidenceScore > 0.7 "
            "| project Latitude, Longitude, HazardType, ConfidenceScore, GForceZ, GaussianSplatURL"
        )

        table = get_kusto_client().execute(db, query).primary_results[0]
        cols = [c.column_name for c in table.columns]
        results = [dict(zip(cols, row)) for row in table.rows]
        return json_response(results, 200)

    except ValueError as ve:
        return json_response({"error": str(ve)}, 400)
    except Exception as e:
        logging.error("Regional KQL Error", exc_info=True)
        return json_response({"error": str(e)}, 500)