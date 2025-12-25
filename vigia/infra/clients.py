import os
import threading

from ..core.config import require_env


_CLIENTS = {}  # lazy singletons per worker
_LOCK = threading.Lock()


def get_auth_credential():
    with _LOCK:
        if "credential" not in _CLIENTS:
            from azure.identity import DefaultAzureCredential
            _CLIENTS["credential"] = DefaultAzureCredential()
        return _CLIENTS["credential"]


# ---------- Lazy client factories ----------

def get_kusto_client():
    if "kusto" in _CLIENTS:
        return _CLIENTS["kusto"]

    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    cluster = require_env("FABRIC_KUSTO_CLUSTER")
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        cluster, get_auth_credential()
    )
    client = KustoClient(kcsb)

    with _LOCK:
        _CLIENTS["kusto"] = client
    return client


def get_project_client():
    if "project_client" in _CLIENTS:
        return _CLIENTS["project_client"]

    from azure.ai.projects import AIProjectClient

    endpoint = (
        os.environ.get("PROJECT_ENDPOINT")
        or os.environ.get("AI_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_ENDPOINT")
    )
    if not endpoint:
        raise RuntimeError("Missing AI project endpoint. Set AI_PROJECT_ENDPOINT (recommended).")

    client = AIProjectClient(endpoint=endpoint, credential=get_auth_credential())

    with _LOCK:
        _CLIENTS["project_client"] = client
    return client


def get_ledger_service_cert_pem() -> str:
    if "ledger_tls_pem" in _CLIENTS:
        return _CLIENTS["ledger_tls_pem"]

    from azure.confidentialledger.certificate import ConfidentialLedgerCertificateClient

    ledger_id = require_env("CONFIDENTIAL_LEDGER_ID")
    identity_url = os.environ.get("CONFIDENTIAL_LEDGER_IDENTITY_URL") or "https://identity.confidential-ledger.core.azure.com"

    cert_client = ConfidentialLedgerCertificateClient(identity_url)
    ident = cert_client.get_ledger_identity(ledger_id)
    pem = ident.get("ledgerTlsCertificate")
    if not pem:
        raise RuntimeError("Unable to fetch ledgerTlsCertificate from identity service")

    with _LOCK:
        _CLIENTS["ledger_tls_pem"] = pem
    return pem


def get_ledger_cert_path() -> str:
    if "ledger_cert_path" in _CLIENTS and os.path.exists(_CLIENTS["ledger_cert_path"]):
        return _CLIENTS["ledger_cert_path"]

    pem = get_ledger_service_cert_pem()
    ledger_id = require_env("CONFIDENTIAL_LEDGER_ID")
    path = f"/tmp/acl_{ledger_id}.pem"

    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(pem)

    with _LOCK:
        _CLIENTS["ledger_cert_path"] = path
    return path