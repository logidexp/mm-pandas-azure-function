import azure.functions as func
import json
from core import enhanced_recommedation

app = func.FunctionApp()

@app.route(route="api", auth_level=func.AuthLevel.FUNCTION)
def get_enhanced_recommendation_for_exhibitor(req: func.HttpRequest) -> func.HttpResponse:

    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
             "No body is provided.",
             status_code=400
        )

    event_id = req_body.get("event")
    exhibitor_id = req_body.get("exhibitor_id")
    min_scans = req_body.get("min_scans", "10")
    exclude = req_body.get("exclude", [])
    apply_degradation = req_body.get("apply_degradation", "false")

    if not (event_id and exhibitor_id):
        return func.HttpResponse(
            "Missing parameters in request event_id and exhibitor_id are mandatory.",
            status_code = 400
        )

    try:
        enhanced_result = enhanced_recommedation(
            event_id=int(event_id),
            exhibitor_id=int(exhibitor_id),
            min_scans=int(min_scans),
            exclude=exclude,
            apply_degradation=apply_degradation
        )
    except Exception as e:
        return func.HttpResponse(
            f"Failed to get recommendation.",
            status_code = 500
        )


    return func.HttpResponse(
        json.dumps(enhanced_result),
        status_code=200,
        mimetype="application/json"
    )