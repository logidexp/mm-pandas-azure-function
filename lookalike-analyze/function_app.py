import azure.functions as func
import json
from core import analyze_event_lookalike

app = func.FunctionApp()

@app.route(route="api", auth_level=func.AuthLevel.FUNCTION)
def get_lead_scan_analyze_for_event(req: func.HttpRequest) -> func.HttpResponse:

    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
             "No body is provided.",
             status_code=400
        )

    try:
        event_id = req_body.get("event")
        min_scans = req_body.get("min_scans", "10")
        apply_degradation = req_body.get("apply_degradation", "false")
    except Exception as e:
        return func.HttpResponse(
            "Bad Request",
            status_code = 400
        )

    if not event_id:
        return func.HttpResponse(
            "Missing parameters in request event_id is mandatory.",
            status_code = 422
        )

    try:
        analyze_result = analyze_event_lookalike(
            event_id=int(event_id),
            min_scans=int(min_scans),
            apply_degradation=apply_degradation
        )
    except ValueError as ve:
        return func.HttpResponse(
            str(ve),
            status_code=404,
        )
    except Exception as ee:
        return func.HttpResponse(
            f"Failed to get analyze infomation.{str(e)}",
            status_code=500,
        )

    return func.HttpResponse(
        json.dumps(analyze_result),
        status_code=200,
        mimetype="application/json"
    )