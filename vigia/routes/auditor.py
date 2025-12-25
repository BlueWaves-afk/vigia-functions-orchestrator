import os
import hashlib
import logging
import azure.functions as func

from vigia.core.jsonx import json_response
from vigia.core.timeutil import _to_iso_datetime

from vigia.infra.audit_store import _audit_append, _audit_get_latest
from vigia.infra.dedupe import _compute_event_id, _kql_dedupe_summary
from vigia.infra.policy import _deterministic_verify_gate
from vigia.infra.ledger import _ledger_write_and_verify

from vigia.agents.notes import _agent_note
from vigia.agents.gate import _verification_agent_gate

bp = func.Blueprint()


@bp.route(route="autonomous-auditor", methods=["POST"])
def autonomous_auditor(req: func.HttpRequest) -> func.HttpResponse:
    """
    Fabric Activator entrypoint (kept) + NEW:
    - After deterministic gate passes, require VerificationAgent approval BEFORE ledger write.
    - Store agent reasoning into AuditEvents.VerificationReasoning (and Details.verification_reasoning fallback).
    """
    try:
        event_data = req.get_json() or {}

        payload = dict(event_data)
        payload["Timestamp"] = _to_iso_datetime(payload.get("Timestamp"))
        report_id = str(payload.get("ReportId") or payload.get("reportId") or "")
        device_id = str(payload.get("DeviceId") or payload.get("deviceId") or "")
        payload["ReportId"] = report_id
        payload["DeviceId"] = device_id

        event_id = _compute_event_id(payload)

        _audit_append(event_id, report_id, "RECEIVED", {"payload": payload})

        latest = _audit_get_latest(event_id)
        if latest and latest.get("Status") in ("REJECTED", "LEDGER_WRITTEN", "REWARDED"):
            return json_response(
                {
                    "status": "Idempotent_Return",
                    "event_id": event_id,
                    "latest_status": latest.get("Status"),
                    "latest_details": latest.get("Details"),
                    "verification_reasoning": latest.get("VerificationReasoning"),
                },
                200,
            )

        _audit_append(event_id, report_id, "AUDITING", {"payload": payload, "note": "audit_started"})

        dedupe = _kql_dedupe_summary(payload)
        _audit_append(event_id, report_id, "DEDUPE_DONE", {"payload": payload, **dedupe})

        forensic_agent_id = os.environ.get("FORENSIC_AGENT_ID", "")
        forensic_run = _agent_note(
            forensic_agent_id,
            {"event_id": event_id, "dedupe": dedupe, "payload": payload},
            note_type="forensic_dedupe_note",
        )
        if forensic_run:
            _audit_append(
                event_id,
                report_id,
                "FORENSIC_AGENT_TRIGGERED",
                {"payload": payload, **forensic_run, "agent": "ForensicAnalyst"},
            )

        ok, reason, score = _deterministic_verify_gate(payload)

        # Keep the existing async note (doesn't gate)
        verification_agent_id = os.environ.get("VERIFICATION_AGENT_ID", "")
        vrun = _agent_note(
            verification_agent_id,
            {"event_id": event_id, "policy_ok": ok, "reason": reason, "score": score, "payload": payload},
            note_type="verification_audit_note",
        )
        if vrun:
            _audit_append(
                event_id,
                report_id,
                "VERIFICATION_AGENT_TRIGGERED",
                {"payload": payload, **vrun, "agent": "VerificationAgent"},
            )

        if not ok:
            _audit_append(
                event_id,
                report_id,
                "REJECTED",
                {"payload": payload, "reason": reason, "score": score, "dedupe": dedupe},
                verification_reasoning=f"Deterministic gate rejected: {reason} (confidence={score})",
            )
            return json_response(
                {
                    "status": "Rejected",
                    "event_id": event_id,
                    "reason": reason,
                    "confidence": score,
                    "dedupe": dedupe,
                },
                200,
            )

        # ---------- NEW: VerificationAgent must approve BEFORE ledger write ----------
        verdict, vmsg = _verification_agent_gate(
            verification_agent_id,
            {
                "event_id": event_id,
                "payload": payload,
                "dedupe": dedupe,
                "deterministic_gate": {"ok": ok, "reason": reason, "score": score},
                "expected_action": "approve_before_ledger_write",
            },
        )

        if verdict is None:
            _audit_append(
                event_id,
                report_id,
                "REJECTED",
                {"payload": payload, "reason": "verification_agent_no_verdict", "note": vmsg, "dedupe": dedupe},
                verification_reasoning="VerificationAgent did not provide a verdict in time (or failed).",
            )
            return json_response(
                {"status": "Rejected", "event_id": event_id, "reason": "verification_agent_no_verdict"},
                200,
            )

        approve = bool(verdict.get("approve"))
        reasoning = str(verdict.get("reasoning") or "").strip()
        quality_score = verdict.get("quality_score", None)

        _audit_append(
            event_id,
            report_id,
            "VERIFICATION_AGENT_VERDICT",
            {"payload": payload, "approve": approve, "quality_score": quality_score, "verdict": verdict},
            verification_reasoning=reasoning,
        )

        if not approve:
            _audit_append(
                event_id,
                report_id,
                "REJECTED",
                {"payload": payload, "reason": "verification_agent_rejected", "quality_score": quality_score, "verdict": verdict},
                verification_reasoning=reasoning or "VerificationAgent rejected without reasoning.",
            )
            return json_response(
                {"status": "Rejected", "event_id": event_id, "reason": "verification_agent_rejected"},
                200,
            )

        # If approved -> write to ledger
        proof_hash = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        ledger_out = _ledger_write_and_verify(proof_hash)

        _audit_append(
            event_id,
            report_id,
            "LEDGER_WRITTEN",
            {"payload": payload, **ledger_out},
            verification_reasoning=reasoning,
        )

        return json_response(
            {
                "status": "Verified",
                "event_id": event_id,
                "dedupe": dedupe,
                "ledger": ledger_out,
                "verification_reasoning": reasoning,
            },
            200,
        )

    except Exception as e:
        logging.error("Sentinel Failure", exc_info=True)
        return json_response({"error": str(e)}, 500)