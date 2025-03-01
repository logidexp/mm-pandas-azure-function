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


def get_event_exhibitors_with_category(event: int, exhibitor_id: int):
    query = f"SELECT category_id FROM dwh.mm.precomputed_exhibitors_{event} WHERE ExhibitorID = {exhibitor_id}"
    cursor.execute(query)
    exhibitor_category = cursor.fetchall()
    df_exhibitor_category = pd.DataFrame(exhibitor_category, columns=["category_id"])

    return df_exhibitor_category


def get_weight_mapping_to_category(event: int):
    query = f"SELECT category_id, answer, weight FROM dwh.mm.precomputed_mapping_{event}"
    cursor.execute(query)
    match_weights = cursor.fetchall()
    df_match_weights = pd.DataFrame(match_weights, columns=["category_id", "answer_id", "weight"])

    return df_match_weights


def get_buying_probability_weight(event: int):
    query = f"SELECT answer, weight FROM dwh.mm.precomputed_scoring_{event}"
    cursor.execute(query)
    buying_scores = cursor.fetchall()
    df_buying_scores = pd.DataFrame(buying_scores, columns=["answer", "weight"])

    return df_buying_scores


def get_enhancing_categories(
    df_lead_scan_data,
    df_visitor_answers,
    df_match_weights
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
        how="right"
    )

    category_list_per_exhibitor = (
        df_visitor_mapping_with_weight.groupby("exhibitor_id")["category_id"]
        .apply(lambda x: list(set(x)))
        .reset_index(name="category_ids")
    )

    return category_list_per_exhibitor


def get_recommended_visitors(
    df_match_weights: pd.DataFrame,
    df_buying_scores: pd.DataFrame,
    df_user_data: pd.DataFrame,
    apply_degradation: bool = False
):
    df_user_data_exploded = df_user_data.explode("user_answers")

    df_match_buying_scores = pd.merge(
        df_user_data_exploded,
        df_buying_scores,
        left_on="user_answers",
        right_on="answer",
        how="left"
    ).groupby(["user_email"], as_index=False)["weight"].sum().rename(columns={"weight": "score"})

    df_category_matches_scores = pd.merge(
        df_user_data_exploded,
        df_match_weights,
        left_on="user_answers",
        right_on="answer_id",
        how="left"
    ).groupby(["user_email"], as_index=False)["weight"].sum().rename(columns={"weight": "score"})

    df_user_scores = pd.merge(
        df_match_buying_scores,
        df_category_matches_scores,
        on=["user_email"],
        suffixes=("_buying", "_category"),
        how="outer"
    )

    df_user_scores["score_buying"] = df_user_scores["score_buying"].fillna(0)
    df_user_scores["score_category"] = df_user_scores["score_category"].fillna(0)

    df_user_scores["total_score"] = df_user_scores["score_buying"] + df_user_scores["score_category"]

    if apply_degradation:
        df_user_category_count = pd.merge(
            df_user_data_exploded,
            df_match_weights,
            left_on="user_answers",
            right_on="answer_id",
            how="inner"
        ).groupby(["user_email"], as_index=False)["category_id"].count().rename(columns={"category_id": "category_count"})

        df_user_scores = pd.merge(
            df_user_scores,
            df_user_category_count,
            on="user_email",
            how="left"
        )
        df_user_scores["total_score"] = df_user_scores["total_score"] / (
            1 + df_user_scores["category_count"].apply(lambda x: math.log(x) if x > 0 else 0)
        )

    df_user_scores = df_user_scores.sort_values(by="total_score", ascending=False)[["user_email", "total_score"]]

    return df_user_scores


def get_event_visitors_detail(event: int, exclude: list):
    query = f"SELECT wisent_user_id, email, answer_ids FROM dwh.mm.precomputed_visitors_{event}"
    cursor.execute(query)
    user_data = cursor.fetchall()
    df_user_data = pd.DataFrame(user_data, columns=["user_id", "user_email", "user_answers"])
    df_user_data = df_user_data[~df_user_data["user_email"].isin(exclude)]

    return df_user_data


def enhanced_recommedation(
        event_id: int,
        exhibitor_id: int,
        min_scans: int,
        exclude: list = [],
        apply_degradation: bool = False
    ):
    df_exhibitor_category = get_event_exhibitors_with_category(event_id, exhibitor_id)
    original_category_list = df_exhibitor_category["category_id"].tolist()

    df_lead_scan_data = get_lead_scan_data(event_id, min_scans)
    df_visitor_answers = get_visitor_with_answers(event_id)
    df_match_weights = get_weight_mapping_to_category(event_id)
    enhancing_category_list = get_enhancing_categories(
        df_lead_scan_data = df_lead_scan_data,
        df_visitor_answers = df_visitor_answers,
        df_match_weights = df_match_weights
    )
    enhancing_category_list = enhancing_category_list.loc[enhancing_category_list["exhibitor_id"] == str(exhibitor_id), "category_ids"].tolist()
    if len(enhancing_category_list) > 0:
        enhancing_category_list = enhancing_category_list[0]

    df_user_data = get_event_visitors_detail(event_id, exclude)
    df_buying_scores = get_buying_probability_weight(event_id)

    df_origin_recommended_visitors = get_recommended_visitors(
        df_match_weights=df_match_weights[df_match_weights["category_id"].isin(original_category_list)],
        df_buying_scores=df_buying_scores,
        df_user_data=df_user_data,
        apply_degradation=apply_degradation
    )

    df_enhancing_recommended_visitors = get_recommended_visitors(
        df_match_weights=df_match_weights[df_match_weights["category_id"].isin(enhancing_category_list)],
        df_buying_scores=df_buying_scores,
        df_user_data=df_user_data,
        apply_degradation=apply_degradation
    )

    enhanced_recommended_visitors = (
        pd.concat([df_origin_recommended_visitors, df_enhancing_recommended_visitors])
        .drop_duplicates(keep=False)
        .reset_index(drop=True)
    )

    origin_recommended_visitors = df_origin_recommended_visitors[["user_email", "total_score"]].to_records(index=False).tolist()
    enhancing_recommended_visitors = df_origin_recommended_visitors[["user_email", "total_score"]].to_records(index=False).tolist()
    enhanced_recommended_visitors = df_origin_recommended_visitors[["user_email", "total_score"]].to_records(index=False).tolist()

    return {
        "original": origin_recommended_visitors,
        "enhanced": enhanced_recommended_visitors,
        "new_matches": enhancing_recommended_visitors
    }