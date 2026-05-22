import azure.functions as func
from core.app import fastapi_app

app = func.AsgiFunctionApp(app=fastapi_app)