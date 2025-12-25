from .message_extract import _as_list


def _run_steps_debug_dump(client, thread_id: str, run_id: str):
    """
    Optional: dump run steps/tool calls to help you see why there is no assistant reply.
    Safe: returns JSON-serializable primitives only.
    """
    def _tool_call_slim(tc):
        # tc may be a model object; keep minimal, safe fields
        if tc is None:
            return None

        # dict-like
        if isinstance(tc, dict):
            slim = {}
            for k in ("id", "type", "name", "status"):
                if k in tc and tc[k] is not None:
                    slim[k] = tc[k]
            slim["repr"] = str(tc)
            return slim

        # object-like
        slim = {}
        for k in ("id", "type", "name", "status"):
            try:
                v = getattr(tc, k, None)
                if v is not None:
                    slim[k] = v
            except Exception:
                pass
        # best-effort string representation
        try:
            slim["repr"] = str(tc)
        except Exception:
            slim["repr"] = "<non-serializable-tool-call>"
        return slim

    try:
        if not hasattr(client, "run_steps"):
            return None
        if not hasattr(client.run_steps, "list"):
            return None

        steps = _as_list(client.run_steps.list(thread_id=thread_id, run_id=run_id))
        out = []
        for s in steps:
            # step may be dict-like
            sid = getattr(s, "id", None) or (s.get("id") if isinstance(s, dict) else None)
            st = getattr(s, "status", None) or (s.get("status") if isinstance(s, dict) else None)
            details = getattr(s, "step_details", None) or (s.get("step_details") if isinstance(s, dict) else {}) or {}

            # normalize details if it's an object
            if not isinstance(details, dict):
                if hasattr(details, "as_dict"):
                    try:
                        details = details.as_dict()
                    except Exception:
                        details = {"repr": str(details)}
                else:
                    details = {"repr": str(details)}

            tool_calls = details.get("tool_calls") or []
            # normalize tool_calls list
            if not isinstance(tool_calls, list):
                tool_calls = [tool_calls]

            out.append({
                "step_id": sid,
                "status": st,
                "tool_calls_count": len(tool_calls),
                "tool_calls": [_tool_call_slim(x) for x in tool_calls[:5]],  # cap + JSON-safe
            })
        return out
    except Exception:
        return None