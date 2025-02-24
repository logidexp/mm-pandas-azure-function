import azure.functions as func
import json
from core import enhanced_recommedation

app = func.FunctionApp()

@app.route(route="lookalike/{event_id}/exhibitors/{exhibitor_id}", auth_level=func.AuthLevel.ANONYMOUS)
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
    min_scans = req_body.get("min_scans")
    exclude = req_body.get("exclude", [])
    apply_degradation = req_body.get("apply_degradation", "false")

    if not (event_id and exhibitor_id and min_scans):
        return func.HttpResponse(
            "Missing parameters in request event_id ,exhibitor_id and min_scans are mandatory.",
            status_code = 400
        )

    enhanced_result = enhanced_recommedation(
        event_id=event_id,
        exhibitor_id=exhibitor_id,
        min_scans=min_scans,
        exclude=exclude,
        apply_degradation=apply_degradation
    )

    return func.HttpResponse(
        json.dumps(enhanced_result),
        status_code=200,
        mimetype="application/json"
    )