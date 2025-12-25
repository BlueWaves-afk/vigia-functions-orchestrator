import hashlib

from ..core.config import require_env
from .clients import get_auth_credential, get_ledger_cert_path, get_ledger_service_cert_pem


def _ledger_write_and_verify(proof_hash: str) -> dict:
    from azure.confidentialledger import ConfidentialLedgerClient
    from azure.confidentialledger.receipt import verify_receipt

    ledger_url = require_env("CONFIDENTIAL_LEDGER_URL")

    ledger_client = ConfidentialLedgerClient(
        endpoint=ledger_url,
        credential=get_auth_credential(),
        ledger_certificate_path=get_ledger_cert_path(),
    )

    write_result = ledger_client.begin_create_ledger_entry({"contents": proof_hash}).result()
    tx_id = write_result.get("transactionId")
    if not tx_id:
        raise RuntimeError(f"Ledger write succeeded but no transactionId returned: {write_result}")

    receipt_result = ledger_client.begin_get_receipt(tx_id).result()
    service_cert_pem = get_ledger_service_cert_pem()
    application_claims = receipt_result.get("applicationClaims")

    verify_receipt(
        receipt_result["receipt"],
        service_cert_pem,
        application_claims=application_claims,
    )

    return {
        "transactionId": tx_id,
        "receipt_verified": True,
        "service_cert_sha256": hashlib.sha256(service_cert_pem.encode("utf-8")).hexdigest(),
        "receipt_result": receipt_result,
        "proof_hash": proof_hash,
    }