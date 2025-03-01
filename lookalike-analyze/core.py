import os
import math
import pandas as pd
from dotenv import load_dotenv
from databricks import sql

load_dotenv()


connection = sql.connect(
    server_hostname = os.environ.get("DATABRICKS_HOST"),
    http_path = os.environ.get("DATABRICKS_HTTP_PATH"),
    access_token = os.environ.get("DATABRICKS_TOKEN"),
)
cursor = connection.cursor()


def get_visitor_with_answers(event_id):
    query = f"SELECT email, answer_ids FROM dwh.mm.precomputed_visitors_{event_id}"
    cursor.execute(query)
    answers = cursor.fetchall()
    df_answers = pd.DataFrame(answers, columns=["visitor_email", "answer_ids"])

    return df_answers


def get_weight_mapping_to_category(event_id: int):
    query = f"SELECT category_id, answer, weight FROM dwh.mm.precomputed_mapping_{event_id}"
    cursor.execute(query)
    match_weights = cursor.fetchall()
    df_match_weights = pd.DataFrame(match_weights, columns=["category_id", "answer_id", "weight"])

    return df_match_weights


def get_lead_scan_data(event_id: int, min_scans: int):
    query = f"""
        SELECT VisitorEmail, ExhibitorCatalogueId
        FROM dwh.mm.precomputed_leadscan_{event_id}
    """
    cursor.execute(query)
    lead_scan_data = cursor.fetchall()
    df_ls_data = pd.DataFrame(lead_scan_data, columns=["visitor_email", "exhibitor_id"])
    
    scan_counts = df_ls_data["exhibitor_id"].value_counts()
    scanned_exhibitors = scan_counts[scan_counts > min_scans].index
    qualify_ls_data = df_ls_data[df_ls_data["exhibitor_id"].isin(scanned_exhibitors)]

    return qualify_ls_data


def get_analyze_info(
    df_lead_scan_data,
    df_visitor_answers,
    df_match_weights,
    apply_degradation: bool = False
):
    df_scanned_visitors = pd.merge(
        df_lead_scan_data,
        df_visitor_answers,
        on=["visitor_email"],
        how="inner"
    )

    df_scanned_visitors_exploded = df_scanned_visitors.explode("answer_ids").rename(columns={"answer_ids": "answer_id"})

    df_visitor_mapping_with_weight = pd.merge(
        df_scanned_visitors_exploded,
        df_match_weights,
        on=["answer_id"],
        how="left"
    )

    visitor_email_per_exhibitor = (
        df_visitor_mapping_with_weight.groupby("exhibitor_id", as_index=False)["visitor_email"]
        .apply(lambda emails: list(set(emails)))
    )

    category_counts_list_per_exhibitor = (
        df_visitor_mapping_with_weight.groupby("exhibitor_id")
        .apply(lambda group: list(
            group["category_id"].value_counts().items()
            )
        )
        .reset_index(name="category_with_counts")
    )

    exhibitor_mapping_weight = (
        df_visitor_mapping_with_weight[["exhibitor_id", "category_id", "weight"]]
        .dropna(subset=["category_id"])
    )

    top_categories_weight_per_exhibitor = (
        exhibitor_mapping_weight.groupby(["exhibitor_id", "category_id"], as_index=False)
        .agg(score=("weight", "sum"), count=("category_id", "size"))
        .sort_values(by=["exhibitor_id", "score"], ascending=[True, False])
    )

    if apply_degradation:
        top_categories_weight_per_exhibitor["score"] = top_categories_weight_per_exhibitor["score"] / (
            1 + top_categories_weight_per_exhibitor["count"].apply(math.log)
        )

    top_categories_weight_per_exhibitor = (
        top_categories_weight_per_exhibitor.groupby("exhibitor_id")
        .apply(
            lambda group: list(
                group.head(5)[["category_id", "score", "count"]].itertuples(index=False, name=None)
            )
        )
        .reset_index(name="top_category_list")
    )

    result = pd.merge(
        visitor_email_per_exhibitor,
        top_categories_weight_per_exhibitor,
        on=["exhibitor_id"],
        how="left"
    )

    result = pd.merge(
        result,
        category_counts_list_per_exhibitor,
        on=["exhibitor_id"],
        how="left"
    )

    return result

        

def analyze_event_lookalike(
        event_id: int,
        min_scans: int,
        apply_degradation: bool = False 
    ):

    try:
        df_lead_scan_data = get_lead_scan_data(event_id, min_scans)
        df_visitor_answers = get_visitor_with_answers(event_id)
        df_match_weights = get_weight_mapping_to_category(event_id)
    except:
        return {"Error": "Failed to get data from DB"}

    try:
        category_analyze_info = get_analyze_info(
            df_lead_scan_data = df_lead_scan_data,
            df_visitor_answers = df_visitor_answers,
            df_match_weights = df_match_weights,
            apply_degradation = apply_degradation
        )
    except:
        return {"Error": "Failed to analyze data"}

    result = {
        row["exhibitor_id"]: {
            "scanned_visitors": row["visitor_email"],
            "top_interests": row["top_category_list"],
            "category_counts": row["category_with_counts"]
        }
        for _, row in category_analyze_info.iterrows()
    }

    return result