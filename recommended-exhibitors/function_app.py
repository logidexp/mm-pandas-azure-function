import azure.functions as func
from core import recommended_exhibitors_for_visitor_email

app = func.FunctionApp()

@app.route(route="api", auth_level=func.AuthLevel.FUNCTION)
def get_recommended_exhibitors_for_visitor_email(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
             "No body is provided.",
             status_code=400
        )

    event = req_body.get("event")
    email = req_body.get("email")
    max_count = req_body.get("max")
    exclude = req_body.get("exclude", [])
    apply_degradation = req_body.get("apply_degradation", "false")
    region_filter = req_body.get("region_filter", [])

    if not (event and email):
        return func.HttpResponse(
            "Missing parameters in request event and email are mandatory.",
            status_code = 400
        )

    exclude = [int(ex) for ex in exclude]
    region_filter = [int(region) for region in region_filter]

    try:
        recommendations = recommended_exhibitors_for_visitor_email(
            event=int(event),
            email=email,
            max_count=int(max_count),
            exclude=exclude,
            apply_degradation=apply_degradation,
            region_filter=region_filter
        )
    except Exception as e:
        return func.HttpResponse(
            f"Failed to get recommendation.",
            status_code=500,
        )

    return func.HttpResponse(
        recommendations.model_dump_json(),
        status_code=200,
        mimetype="application/json"
    ) 