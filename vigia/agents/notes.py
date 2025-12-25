import json
import logging

from ..infra.clients import get_project_client


def _agent_note(agent_id: str, payload: dict, note_type: str):
    if not agent_id:
        return None
    try:
        project = get_project_client()
        agents = project.agents

        thread = agents.threads.create()
        agents.messages.create(
            thread_id=thread.id,
            role="user",
            content=json.dumps({"type": note_type, "payload": payload}, ensure_ascii=False),
        )
        run = agents.runs.create(thread_id=thread.id, agent_id=agent_id)

        run_id = getattr(run, "id", None) or (run.get("id") if isinstance(run, dict) else None)
        return {
            "thread_id": getattr(thread, "id", None) or (thread.get("id") if isinstance(thread, dict) else None),
            "run_id": run_id
        }
    except Exception:
        logging.warning("Agent note failed", exc_info=True)
        return None