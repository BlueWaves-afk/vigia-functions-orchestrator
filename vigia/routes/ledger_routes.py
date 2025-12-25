import os
import json
import logging
import azure.functions as func

from vigia.core.jsonx import json_response
from vigia.infra.ledger import _ledger_write_and_verify
from vigia.infra.clients import get_project_client

bp = func.Blueprint()


@bp.route(route="verify-work", methods=["POST"])
def verify_work(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manual ledger write endpoint (kept).
    """
    try:
        body = req.get_json()
        proof_hash = body.get("proof_hash")
        if not proof_hash:
            return json_response({"error": "Missing 'proof_hash' in body"}, 400)

        ledger_out = _ledger_write_and_verify(proof_hash)

        # Optional: send proof bundle to your agent for audit/reasoning (kept)
        agent_run_id = None
        agent_id = os.environ.get("AZURE_AGENT_ID") or os.environ.get("VERIFICATION_AGENT_ID")
        if agent_id:
            try:
                project = get_project_client()
                agents = project.agents

                thread = agents.threads.create()
                agents.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=json.dumps(
                        {"type": "ledger_write_proof", "ledger_out": ledger_out},
                        ensure_ascii=False,
                    ),
                )
                run = agents.runs.create(thread_id=thread.id, agent_id=agent_id)
                agent_run_id = getattr(run, "id", None) or (run.get("id") if isinstance(run, dict) else None)
            except Exception:
                logging.warning("Agent push failed (ledger write still verified).", exc_info=True)

        return json_response(
            {
                "status": "Verified",
                "transactionId": ledger_out["transactionId"],
                "receipt_verified": True,
                "agent_run_id": agent_run_id,
            },
            200,
        )

    except KeyError as ke:
        logging.error("Receipt missing expected field", exc_info=True)
        return json_response({"error": f"Receipt missing field: {str(ke)}"}, 500)
    except Exception as e:
        logging.error("Ledger Error", exc_info=True)
        return json_response({"error": str(e)}, 500)