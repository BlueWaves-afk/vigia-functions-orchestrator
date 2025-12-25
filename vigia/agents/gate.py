import os
import json
import time
import logging
import traceback

from ..infra.clients import _CLIENTS, _LOCK, get_auth_credential
from ..core.config import _parse_int

from .message_extract import _as_list, _extract_assistant_text, _is_model_reply_role, _norm_role, _safe_repr
from .runsteps import _run_steps_debug_dump


def get_agents_client():
    """
    Returns azure.ai.agents.AgentsClient bound to your AI Project endpoint.
    Uses the same endpoint envs you already use for get_project_client().
    """
    if "agents_client" in _CLIENTS:
        return _CLIENTS["agents_client"]

    from azure.ai.agents import AgentsClient

    endpoint = (
        os.environ.get("PROJECT_ENDPOINT")
        or os.environ.get("AI_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_ENDPOINT")
    )
    if not endpoint:
        raise RuntimeError("Missing AI project endpoint. Set AI_PROJECT_ENDPOINT (recommended).")

    client = AgentsClient(endpoint=endpoint, credential=get_auth_credential())

    with _LOCK:
        _CLIENTS["agents_client"] = client
    return client


# ---------------------------
# FINAL: Verification agent gate (blocking)
# ---------------------------
def _verification_agent_gate(agent_id: str, request_payload: dict):
    """
    Blocking call: agent must return JSON:
      {"approve": true/false, "reasoning": "...", "quality_score": 0.0-1.0}

    Returns: (verdict_dict_or_None, status_string_or_error_code)
    """
    if not agent_id:
        return None, "missing_agent_id"

    timeout_s = _parse_int(os.environ.get("VERIFICATION_AGENT_TIMEOUT_SECONDS", "25"), 25, 5, 180)
    poll_s = _parse_int(os.environ.get("VERIFICATION_AGENT_POLL_SECONDS", "1"), 1, 1, 10)

    thread_id = None
    run_id = None
    run_status = None

    try:
        client = get_agents_client()

        # Create thread
        thread = client.threads.create()
        thread_id = getattr(thread, "id", None) or (thread.get("id") if isinstance(thread, dict) else None)
        if not thread_id:
            raise RuntimeError("Thread creation returned no thread_id")

        # Send the request to the agent
        client.messages.create(
            thread_id=thread_id,
            role="user",
            content=json.dumps(
                {
                    "type": "verification_gate_request",
                    "instruction": "Return ONLY valid JSON with keys: approve(bool), reasoning(str), quality_score(number 0..1). No extra text.",
                    "payload": request_payload,
                },
                ensure_ascii=False,
            ),
        )

        # Start run (manual polling is most compatible across SDK versions)
        run = client.runs.create(thread_id=thread_id, agent_id=agent_id)
        run_id = getattr(run, "id", None) or (run.get("id") if isinstance(run, dict) else None)
        if not run_id:
            raise RuntimeError("Run creation returned no run_id")

        deadline = time.time() + timeout_s
        last_error = None

        while time.time() < deadline:
            r = client.runs.get(thread_id=thread_id, run_id=run_id)
            run_status = getattr(r, "status", None) or (r.get("status") if isinstance(r, dict) else None)

            # capture last_error if present
            last_error = getattr(r, "last_error", None) or (r.get("last_error") if isinstance(r, dict) else None)

            if run_status in ("completed", "failed", "cancelled", "requires_action"):
                break
            time.sleep(poll_s)

        if run_status != "completed":
            # include last_error + steps to help diagnose
            steps_dump = _run_steps_debug_dump(client, thread_id, run_id)
            return None, {
                "error": "agent_run_not_completed",
                "thread_id": thread_id,
                "run_id": run_id,
                "status": run_status,
                "last_error": last_error,
                "run_steps": steps_dump,
            }

        # Read messages (IMPORTANT: messages.list is often paged/iterable, not dict.data)
        try:
            # if enums exist, use them; otherwise fall back to raw args
            from azure.ai.agents.models import ListSortOrder
            msgs_obj = client.messages.list(thread_id=thread_id, order=ListSortOrder.DESCENDING, limit=50)
        except Exception:
            msgs_obj = client.messages.list(thread_id=thread_id, limit=50)

        items = _as_list(msgs_obj)

        # Find first agent/assistant message in the returned order (usually newest-first)
# Read messages, find latest model reply (assistant OR agent)
# Read messages, find latest model reply (assistant OR agent)
        try:
            msgs = client.messages.list(thread_id=thread_id)  # safest signature
        except TypeError:
            # if your SDK supports limit/order, fine; but don't rely on it
            msgs = client.messages.list(thread_id=thread_id, limit=20, order="desc")

        items = _as_list(msgs, limit=50)

        assistant_msg = None
        roles_seen = []
        for m in items:
            role = getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else None)
            rnorm = _norm_role(role)
            roles_seen.append(rnorm)
            if _is_model_reply_role(rnorm):
                assistant_msg = m
                break

        if not assistant_msg:
            return None, {
                "error": "no_assistant_reply",
                "thread_id": thread_id,
                "run_id": run_id,
                "status": run_status,
                "roles_seen": roles_seen,
                "messages_count": len(items),
                "messages_preview": [_safe_repr(x) for x in items[:3]],
                "run_steps": _run_steps_debug_dump(client, thread_id, run_id),
            }

        text = _extract_assistant_text(assistant_msg).strip()
        if not text:
            steps_dump = _run_steps_debug_dump(client, thread_id, run_id)
            return None, {
                "error": "empty_assistant_reply",
                "thread_id": thread_id,
                "run_id": run_id,
                "status": run_status,
                "run_steps": steps_dump,
            }

        verdict = json.loads(text)
        if "approve" not in verdict:
            return None, {
                "error": "missing_approve_field",
                "thread_id": thread_id,
                "run_id": run_id,
                "status": run_status,
                "assistant_text": text[:5000],
            }

        return verdict, "ok"

    except Exception as e:
        return None, {
            "error": "agent_gate_exception",
            "thread_id": thread_id,
            "run_id": run_id,
            "status": run_status,
            "exc_type": type(e).__name__,
            "message": str(e),
            "trace": traceback.format_exc(),
        }