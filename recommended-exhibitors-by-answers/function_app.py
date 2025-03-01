import azure.functions as func
from core import recommended_exhibitors_by_answers

app = func.FunctionApp()

@app.route(route="api", auth_level=func.AuthLevel.FUNCTION)
def get_recommended_exhibitors_by_answers(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
             "No body is provided.",
             status_code=400
        )

    try:
        event = req_body.get("event")
        answers = req_body.get("answers")
        max_count = req_body.get("max")
        exclude = req_body.get("exclude", [])
        apply_degradation = req_body.get("apply_degradation", "false")
        region_filter = req_body.get("region_filter", [])
    except Exception as e:
        return func.HttpResponse(
            "Bad Request",
            status_code = 400
        )

    if not (event and answers):
        return func.HttpResponse(
            "Missing parameters in request event and answer are mandatory.",
            status_code = 422
        )

    exclude = [int(ex) for ex in exclude]
    region_filter = [int(region) for region in region_filter]

    try:
        recommendations = recommended_exhibitors_by_answers(
            event=int(event),
            answers=answers,
            max_count=int(max_count),
            exclude=exclude,
            apply_degradation=apply_degradation,
            region_filter=region_filter
        )
    except ValueError as ve:
        return func.HttpResponse(
            str(ve),
            status_code=404,
        )
    except Exception as ee:
        return func.HttpResponse(
            f"Failed to get recommendation.\n{str(ee)}",
            status_code=500,
        )

    return func.HttpResponse(
        recommendations.model_dump_json(),
        status_code=200,
        mimetype="application/json"
    ) 