import os


def _deterministic_verify_gate(payload: dict) -> (bool, str, float):
    threshold = float(os.environ.get("VERIFY_CONFIDENCE_THRESHOLD", "0.7"))

    hazard_type = (payload.get("HazardType") or "none").strip().lower()
    conf = float(payload.get("ConfidenceScore") or 0.0)
    url = (payload.get("GaussianSplatURL") or "").strip().lower()

    if hazard_type in ("none", "", "unknown"):
        return False, "hazard_type_none", conf
    if conf < threshold:
        return False, f"confidence_below_{threshold}", conf
    if url in ("", "pending") and hazard_type not in ("red_light_violation",):
        return False, "missing_evidence_url", conf

    return True, "passed_policy_gate", conf