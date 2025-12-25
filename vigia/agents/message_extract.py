import itertools


def _message_role_str(msg):
    """
    Normalize role field across SDK versions.
    """
    role = getattr(msg, "role", None)
    if role is None and isinstance(msg, dict):
        role = msg.get("role")
    return str(role).lower() if role is not None else ""


def _extract_assistant_text(message_obj) -> str:
    """
    Try hard to extract the assistant/agent reply text from azure-ai-agents message objects.
    Supports:
      - message.text_messages[*].text.value (common)
      - message.content (list/dict/string fallbacks)
      - dict shapes
    """
    # 1) SDK-native: text_messages
    try:
        tms = getattr(message_obj, "text_messages", None)
        if tms:
            parts = []
            for tm in tms:
                # tm.text.value is typical
                txt = None
                t = getattr(tm, "text", None)
                if t is not None:
                    txt = getattr(t, "value", None) or getattr(t, "text", None)
                if txt is None and isinstance(tm, dict):
                    t = tm.get("text") or {}
                    txt = t.get("value") or t.get("text")
                if txt:
                    parts.append(str(txt))
            if parts:
                return "\n".join(parts).strip()
    except Exception:
        pass

    # 2) Fallback: content
    content = getattr(message_obj, "content", None)
    if content is None and isinstance(message_obj, dict):
        content = message_obj.get("content")

    # content can be: string OR list of parts OR dict
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict):
                # common shapes: {"type":"text","text":"..."} or {"text":{"value":"..."}}
                if "text" in c and isinstance(c["text"], str):
                    parts.append(c["text"])
                elif "text" in c and isinstance(c["text"], dict):
                    parts.append(str(c["text"].get("value") or c["text"].get("text") or ""))
                elif "value" in c:
                    parts.append(str(c["value"]))
        return "\n".join([p for p in parts if p]).strip()

    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return content["text"].strip()
        if "text" in content and isinstance(content["text"], dict):
            return str(content["text"].get("value") or content["text"].get("text") or "").strip()

    return ""


def _norm_role(role):
    # Handles enums like MessageRole.AGENT and strings like "messagerole.agent"
    if role is None:
        return ""
    v = getattr(role, "value", None)
    if v:
        return str(v).strip().lower()
    return str(role).strip().lower()


def _is_model_reply_role(role_str: str) -> bool:
    rs = (role_str or "").lower()
    return ("assistant" in rs) or (rs.endswith("agent")) or ("messagerole.agent" in rs) or (rs == "agent")


def _as_list(obj, limit: int = 50):
    """
    Convert list/dict-with-data/ItemPaged/iterables into a Python list (capped).
    """
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj[:limit]
    if isinstance(obj, dict):
        data = obj.get("data")
        if isinstance(data, list):
            return data[:limit]
        return []
    # azure.core.paging.ItemPaged or any iterable
    if hasattr(obj, "__iter__"):
        return list(itertools.islice(obj, limit))
    return []


def _safe_repr(x, max_len: int = 1200) -> str:
    try:
        s = repr(x)
    except Exception:
        s = f"<unreprable:{type(x).__name__}>"
    if len(s) > max_len:
        return s[:max_len] + "...<truncated>"
    return s