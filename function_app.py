import azure.functions as func

from vigia.routes.hazards import bp as hazards_bp
from vigia.routes.auditor import bp as auditor_bp
from vigia.routes.ledger_routes import bp as ledger_bp
from vigia.routes.audit_api import bp as audit_bp

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

app.register_functions(hazards_bp)
app.register_functions(auditor_bp)
app.register_functions(ledger_bp)
app.register_functions(audit_bp)