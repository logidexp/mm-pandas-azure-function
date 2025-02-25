import azure.functions as func
from core import recommended_exhibitors_for_visitor_email

app = func.FunctionApp()

@app.route(route="api", auth_level=func.AuthLevel.ANONYMOUS)
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
    exclude = req_body.get("exclude")
    apply_degradation = req_body.get("apply_degradation")

    if not (event and email):
        return func.HttpResponse(
            "Missing parameters in request event and email are mandatory.",
            status_code = 400
        )

    try:
        recommendations = recommended_exhibitors_for_visitor_email(
            event=event,
            email=email,
            max_count=max_count,
            exclude=exclude,
            apply_degradation=apply_degradation 
        )
    except Exception as e:
        return func.HttpResponse(
            "Failed to get recommendation",
            status_code=500,
        )

    return func.HttpResponse(
        recommendations.model_dump_json(),
        status_code=200,
        mimetype="application/json"
    ) 