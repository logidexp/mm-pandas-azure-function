import azure.functions as func
import json
from core import analyze_event_lookalike

app = func.FunctionApp()

@app.route(route="lookalike/{event_id}/exhibitors", auth_level=func.AuthLevel.ANONYMOUS)
def get_lead_scan_analyze_for_event(req: func.HttpRequest) -> func.HttpResponse:

    try:
        event_id = int(req.route_params.get("event_id"))
        min_scans = int(req.params.get("min_scans"))
        apply_degradation = req.params.get("apply_degradation", "False").lower() is "true"
    except Exception as e:
        return func.HttpResponse(
            f"Invalid Request: {str(e)}",
            status_code=400
        )

    try:
        analyze_result = analyze_event_lookalike(
            event_id=event_id,
            min_scans=min_scans,
            apply_degradation=apply_degradation
        )
    except Exception as e:
        return func.HttpResponse(
            f"Failed to get analyze infomation\n{str(e)}",
            status_code=500,
        )

    return func.HttpResponse(
        json.dumps(analyze_result),
        status_code=200,
        mimetype="application/json"
    )