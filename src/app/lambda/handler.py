from mangum import Mangum

from app.main import app

# AWS Lambda entrypoint for API Gateway (REST/HTTP API).
handler = Mangum(app)
