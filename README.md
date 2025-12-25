Below is a drop-in README.md you can copy to your repo root. It’s written to satisfy three audiences at once: engineers, Microsoft/Azure developers, and Imagine Cup judges.

⸻

VIGIA Azure Functions — Deterministic Orchestrator + Agent-Verified Trust Pipeline

VIGIA is a road-hazard intelligence system designed for real-time reporting, verification, and trustable auditability.
This repository contains the serverless “orchestrator of truth” implemented as Azure Functions (Python), modularized for readability and judge/engineer review.

The core goal of this codebase is to make every hazard report:
	•	Idempotent (safe to retry; same input → same EventId)
	•	Auditable (append-only state transitions in Fabric/Kusto)
	•	Verifiable (human-interpretable reasoning from an agent gate)
	•	Tamper-evident (proof hash committed to Azure Confidential Ledger + receipt verification)

⸻

Why this architecture wins (and why we chose it)

Deterministic pipeline (serverless “source of truth”)

The Azure Function App is intentionally deterministic:
	•	It computes a stable EventId from payload features (lat/lon bucketing, time bucketing, hazard type, evidence hash).
	•	It writes append-only audit events in a strict lifecycle.
	•	It only performs ledger writes when policy + agent gate approve.

This makes the pipeline predictable, testable, retry-safe, and judge-friendly.

Two-layer verification: policy gate + agent gate

We use:
	1.	A deterministic policy gate (fast, explainable thresholds)
	2.	A blocking Verification Agent gate (requires structured JSON verdict: approve + reasoning + quality score)

This prevents expensive ledger writes for low-quality events and produces reasoning that can be shown to users, auditors, and reviewers.

Trust anchoring via Confidential Ledger receipts

When approved, we write a proof hash to Azure Confidential Ledger and then verify the receipt server-side.
That provides strong integrity guarantees and a clean compliance story.

⸻

Repository layout

.
├─ function_app.py
├─ host.json
├─ local.settings.json              # DO NOT COMMIT (secrets)
├─ requirements.txt
└─ vigia/
   ├─ __init__.py
   ├─ routes/
   │  ├─ __init__.py
   │  ├─ hazards.py
   │  ├─ auditor.py
   │  ├─ ledger_routes.py
   │  └─ audit_api.py
   ├─ core/
   │  ├─ __init__.py
   │  ├─ config.py
   │  ├─ jsonx.py
   │  ├─ kql.py
   │  └─ timeutil.py
   ├─ infra/
   │  ├─ __init__.py
   │  ├─ clients.py
   │  ├─ audit_store.py
   │  ├─ dedupe.py
   │  ├─ policy.py
   │  └─ ledger.py
   └─ agents/
      ├─ __init__.py
      ├─ gate.py
      ├─ message_extract.py
      ├─ runsteps.py
      └─ notes.py

Note on modularization: This repo is a clean split of the original working function_app.py into modules without changing logic or naming, only moving code into well-scoped files.

⸻

Entry point

function_app.py

Purpose: Azure Functions runtime entrypoint.

Key design choice: We use the Blueprint registration pattern (Option B):
	•	Each route module exposes bp = func.Blueprint()
	•	function_app.py registers these blueprints into a single FunctionApp

Why this is preferred:
	•	Avoids fragile “import side-effect” route registration
	•	Reduces circular import risk
	•	Improves modularity and readability for reviewers

⸻

Routes (HTTP endpoints)

All endpoints are defined under vigia/routes/ and registered via blueprints.

vigia/routes/hazards.py

Purpose: Read/query hazard telemetry from Fabric/Kusto (e.g., “top hazards” or hazards within a region).

Endpoints:
	•	GET  /query-hazards?hazard_type=...&time_range_hours=...
	•	POST /get-regional-hazards with bounding box {n,s,e,w}

Design choices:
	•	Keeps querying logic server-side (clients stay thin)
	•	Uses strict parsing helpers for numeric bounds and time windows
	•	Returns JSON using a consistent json_response() wrapper

vigia/routes/auditor.py

Purpose: The main orchestrator endpoint for the hazard trust pipeline.

Endpoint:
	•	POST /autonomous-auditor

Pipeline steps (high level):
	1.	Normalize payload + timestamp
	2.	Compute deterministic event_id
	3.	Append audit state: RECEIVED → AUDITING
	4.	Dedupe summary from telemetry (DEDUPE_DONE)
	5.	Fire async forensic note (optional)
	6.	Deterministic policy gate (_deterministic_verify_gate)
	7.	Fire async verification note (optional)
	8.	Blocking verification agent gate (must approve)
	9.	If approved → ledger write + receipt verification
	10.	Append audit state LEDGER_WRITTEN with reasoning attached

Why judges like this:
	•	It’s a clear, stateful, explainable pipeline
	•	It’s resilient (idempotent) and auditable (append-only)
	•	It produces defensible “why approved/rejected” reasoning

vigia/routes/ledger_routes.py

Purpose: Manual ledger write + receipt verification endpoint.

Endpoint:
	•	POST /verify-work with { "proof_hash": "..." }

This is useful for:
	•	Admin/testing flows
	•	Demonstrating ledger anchoring independent of the full pipeline

vigia/routes/audit_api.py

Purpose: Copilot/UX-friendly audit access (“what happened to my event?”).

Endpoints:
	•	GET /audit-latest?event_id=...
	•	GET /audit-history?event_id=...&limit=...
	•	GET /audit-explain?event_id=...

Why this matters:
	•	Enables a human-facing copilot to explain outcomes
	•	Supports review workflows and dispute resolution
	•	Makes audit trails easy to consume

⸻

Core utilities (pure helpers)

vigia/core/config.py

Purpose: Configuration resolution and parameter parsing.
	•	require_env() hard-fails on missing mandatory env vars
	•	_parse_int(), _parse_float() enforce safe numeric conversion
	•	get_kusto_db_name(), get_audit_table_name() centralize naming

Design choice:
	•	Centralized env resolution prevents scattered “magic strings”
	•	Strong parsing avoids silent runtime failures and messy query bugs

vigia/core/jsonx.py

Purpose: JSON serialization utilities for Azure Functions responses.
	•	Handles datetime and SDK objects safely (_json_default, _json_fallback)
	•	Provides json_response(payload, status_code)

Design choice:
	•	Kusto/SDK often returns objects/datetimes that break json.dumps
	•	This guarantees stable API responses for clients and tests

vigia/core/kql.py

Purpose: KQL safety helpers.
	•	_escape_kql_string() prevents quote breaking / malformed KQL

vigia/core/timeutil.py

Purpose: Time normalization and rounding primitives.
	•	_to_iso_datetime() accepts ISO strings or epoch ms
	•	_utc_now_iso() provides server authoritative timestamps
	•	_round_float() normalizes lat/lon bucketing inputs

⸻

Infrastructure layer (external systems + state)

vigia/infra/clients.py

Purpose: Lazy, thread-safe singleton creation for Azure SDK clients.
	•	DefaultAzureCredential cached per worker
	•	Kusto client factory
	•	Project client factory (Azure AI Projects)
	•	Confidential Ledger certificate/PEM fetch + cert path caching

Design choices:
	•	Lazy init reduces cold-start cost
	•	Cached singletons reduce per-request overhead
	•	Cert PEM is fetched once and stored locally for TLS validation

vigia/infra/audit_store.py

Purpose: Append-only audit logging in Fabric/Kusto.

Functions:
	•	_audit_append(event_id, report_id, status, details, verification_reasoning="")
	•	_audit_get_latest(event_id)
	•	_audit_has_verification_reasoning_col() (schema capability check)

Key design choices:
	•	Append-only audit entries create a timeline of truth
	•	Reasoning is stored both in:
	•	AuditEvents.VerificationReasoning column (if present)
	•	and/or Details.verification_reasoning fallback

This makes the system robust across schema versions.

vigia/infra/dedupe.py

Purpose: Deterministic idempotency + Kusto dedupe summary.
	•	_compute_event_id(payload) builds stable hash from bucketed features
	•	_kql_dedupe_summary(payload) checks duplicates in recent telemetry

Design choice:
	•	Dedupe does not “delete” anything; it summarizes and informs decisions
	•	Stable EventId is the backbone of retry-safe pipelines

vigia/infra/policy.py

Purpose: Deterministic verification gate (fast, explainable).
	•	Rejects missing hazard type
	•	Rejects low confidence
	•	Rejects missing evidence URL (except allowed types)

Design choice:
	•	This gate reduces agent/ledger cost and improves system quality

vigia/infra/ledger.py

Purpose: Writes proof to Confidential Ledger and verifies receipt.
	•	_ledger_write_and_verify(proof_hash) performs:
	•	ledger entry creation
	•	receipt retrieval
	•	receipt verification using service cert

Design choice:
	•	Receipt verification ensures integrity and correct anchoring at runtime, not just “we wrote something”.

⸻

Agents layer (reasoning + debugging)

vigia/agents/gate.py

Purpose: Blocking Verification Agent gate.
	•	Requires strict JSON output:

{"approve": true/false, "reasoning": "...", "quality_score": 0..1}


	•	Polls run status with timeout controls
	•	Returns detailed diagnostics if agent doesn’t respond

Why this matters:
	•	Judges want explainability
	•	Engineers want structured contracts and clear failure modes

vigia/agents/message_extract.py

Purpose: Robust extraction of agent reply text across SDK shape differences.
	•	Handles multiple message formats across versions
	•	Normalizes roles and safely previews messages for debugging

vigia/agents/runsteps.py

Purpose: Debug introspection for agent run steps/tool calls.
	•	Helps diagnose “no assistant reply” situations without crashing responses

vigia/agents/notes.py

Purpose: Non-blocking agent “notes” (asynchronous intelligence).
	•	Forensic Analyst notes for dedupe/trends
	•	Verification notes for contextual reasoning
	•	These do not gate decisions; they enrich the audit trail

⸻

Security: no hardcoded keys, safe to publish?

✅ No hardcoded API keys/URLs should exist in code

This architecture is built to read all sensitive configuration from environment variables using require_env() / os.environ.get().

⚠️ What you MUST do before pushing to GitHub
	1.	Do not commit local.settings.json (should be in .gitignore)
	2.	Scan for secrets anyway:

git grep -nE "api[_-]?key|secret|token|password|connectionstring|sas|bearer" .


	3.	Prefer Azure Key Vault + App Settings references in production.

If you want, paste your .gitignore and local.settings.json (with values redacted) and I’ll confirm it’s safe.

⸻

Deployment: will this deploy cleanly?

Yes—if your Function App has:
	•	Python runtime configured correctly
	•	requirements.txt installed successfully
	•	App Settings configured (env vars below)
	•	Route prefix expectation matches (/api/... default)

Because your routes are blueprint-registered through function_app.py, deployment should behave consistently.

⸻

Required environment variables

Kusto / Fabric
	•	FABRIC_KUSTO_CLUSTER (required)
	•	FABRIC_DB_NAME (optional fallback) or FABRIC_KUSTO_DB
	•	AUDIT_TABLE_NAME (optional, default: AuditEvents)

Azure AI Project / Agents
	•	AI_PROJECT_ENDPOINT (recommended) or PROJECT_ENDPOINT / AZURE_AI_ENDPOINT
	•	VERIFICATION_AGENT_ID (required for gating)
	•	FORENSIC_AGENT_ID (optional)

Confidential Ledger
	•	CONFIDENTIAL_LEDGER_URL (required)
	•	CONFIDENTIAL_LEDGER_ID (required)
	•	CONFIDENTIAL_LEDGER_IDENTITY_URL (optional)

Policy / Dedupe tuning (optional)
	•	VERIFY_CONFIDENCE_THRESHOLD (default 0.7)
	•	DEDUP_LATLON_DECIMALS (default 3)
	•	DEDUP_TIME_BUCKET_MINUTES (default 60)
	•	AUDIT_IDEMPOTENCY_TTL_HOURS (default 24)
	•	VERIFICATION_AGENT_TIMEOUT_SECONDS (default 25)
	•	VERIFICATION_AGENT_POLL_SECONDS (default 1)

⸻

Local development

1) Install

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

2) Run Functions locally

func start

By default, endpoints will be under:

http://localhost:7071/api/<route>


⸻

Quick API tests (curl)

Set:

export BASE="http://localhost:7071"

Query hazards

curl -s "$BASE/api/query-hazards?hazard_type=Pothole&time_range_hours=24" | jq

Regional hazards

curl -s -X POST "$BASE/api/get-regional-hazards" \
  -H "Content-Type: application/json" \
  -d '{"n":25.2,"s":25.0,"e":55.4,"w":55.2}' | jq

Run orchestrator

curl -s -X POST "$BASE/api/autonomous-auditor" \
  -H "Content-Type: application/json" \
  -d '{
    "ReportId":"R-123",
    "DeviceId":"D-01",
    "Timestamp": 1735600000000,
    "Latitude": 25.2048,
    "Longitude": 55.2708,
    "HazardType": "pothole",
    "ConfidenceScore": 0.91,
    "GaussianSplatURL":"https://example.com/evidence"
  }' | jq

Audit explain

curl -s "$BASE/api/audit-explain?event_id=<EVENT_ID>" | jq

Manual ledger proof

curl -s -X POST "$BASE/api/verify-work" \
  -H "Content-Type: application/json" \
  -d '{"proof_hash":"abc123..."}' | jq


⸻

Operational guarantees

Idempotency
	•	Deterministic EventId means repeated submissions converge to the same “truth record”.
	•	Audit store short-circuits if already REJECTED / LEDGER_WRITTEN / REWARDED.

Auditability
	•	Append-only timeline of states enables:
	•	debugging,
	•	compliance review,
	•	dispute resolution,
	•	analytics.

Explainability
	•	Policy gate provides deterministic reasons.
	•	Agent gate provides human-readable reasoning that is persisted for later explanation.

Integrity
	•	Confidential Ledger receipt verification ensures the proof is genuinely anchored.

⸻

Notes for Imagine Cup judges

This repository demonstrates:
	•	Responsible AI (agent gate + deterministic safety gate + auditability)
	•	Security and trust (ledger anchoring + receipt verification)
	•	Engineering maturity (idempotency, caching, modular design, failure diagnostics)
	•	Scalability (serverless, stateless compute; externalized state)
	•	Real-world viability (clean endpoints for client apps + copilot UX)

⸻

If you paste your remaining __init__.py files (agents/core/routes) and requirements.txt, I can:
	•	tighten the README to exactly match your import paths,
	•	add a “sequence diagram” section,
	•	and include a “Failure modes & mitigations” table (judges love that).