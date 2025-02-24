import os
import math
import json
import pandas as pd
from dotenv import load_dotenv
from databricks import sql
from typing import List
from schema import VisitorRecommendation, VisitorRecommendations


load_dotenv()


def connect_to_databricks():
    connection = sql.connect(
        server_hostname = os.environ.get("DATABRICKS_HOST"),
        http_path = os.environ.get("DATABRICKS_HTTP_PATH"),
        access_token = os.environ.get("DATABRICKS_TOKEN"),
    )
    return connection


def get_weight_mapping_to_category(event: int):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    query = f"SELECT category_id, answer, weight FROM dwh.mm.precomputed_mapping_{event}"
    cursor.execute(query)
    match_weights = cursor.fetchall()
    df_match_weights = pd.DataFrame(match_weights, columns=["category_id", "answerId", "weight"])

    return df_match_weights


def get_event_exhibitors_with_category(event: int, exclude: List = []):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    query = f"SELECT ExhibitorID, category_id FROM dwh.mm.precomputed_exhibitors_{event}"
    cursor.execute(query)
    exhibitor_category = cursor.fetchall()
    df_exhibitor_category = pd.DataFrame(exhibitor_category, columns=["exhibitor_id", "category_id"])
    df_exhibitor_category = df_exhibitor_category[~df_exhibitor_category["exhibitor_id"].isin(exclude)]

    return df_exhibitor_category


def get_buying_probability_weight(event: int):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    query = f"SELECT answer, weight FROM dwh.mm.precomputed_scoring_{event}"
    cursor.execute(query)
    buying_scores = cursor.fetchall()
    df_buying_scores = pd.DataFrame(buying_scores, columns=["answer", "weight"])

    return df_buying_scores


def get_event_visitors_detail(event: int, exclude: List = []):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    query = f"SELECT wisent_user_id, email, user, answer_ids FROM dwh.mm.precomputed_visitors_{event}"
    cursor.execute(query)
    user_data = cursor.fetchall()
    df_user_data = pd.DataFrame(user_data, columns=["user_id", "user_email", "user_info", "user_answers"])
    df_user_data = df_user_data[~df_user_data["user_id"].isin(exclude)]

    return df_user_data


def get_recommended_visitors(
    df_match_weights: pd.DataFrame,
    df_buying_scores: pd.DataFrame,
    df_user_data: pd.DataFrame,
    max_count: int,
    apply_degradation: bool = False
):
    df_user_data_exploded = df_user_data.explode("user_answers")

    df_match_buying_scores = pd.merge(
        df_user_data_exploded,
        df_buying_scores,
        left_on="user_answers",
        right_on="answer",
        how="left"
    ).groupby(["user_id", "user_email", "user_info"], as_index=False)["weight"].sum().rename(columns={"weight": "score"})

    df_category_matches_scores = pd.merge(
        df_user_data_exploded,
        df_match_weights,
        left_on="user_answers",
        right_on="answerId",
        how="left"
    ).groupby(["user_id", "user_email", "user_info"], as_index=False)["weight"].sum().rename(columns={"weight": "score"})

    df_user_scores = pd.merge(
        df_match_buying_scores,
        df_category_matches_scores,
        on=["user_id", "user_email", "user_info"],
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
            right_on="answerId",
            how="inner"
        ).groupby(["user_id"], as_index=False)["category_id"].count().rename(columns={"category_id": "category_count"})

        df_user_scores = pd.merge(
            df_user_scores,
            df_user_category_count,
            on="user_id",
            how="left"
        )
        df_user_scores["total_score"] = df_user_scores["total_score"] / (
            1 + df_user_scores["category_count"].apply(lambda x: math.log(x) if x > 0 else 0)
        )

    df_user_scores = df_user_scores.sort_values(by="user_id", ascending=True).nlargest(max_count, "total_score")

    df_user_scores["user_info"] = df_user_scores["user_info"].apply(json.loads)

    recommendations = []
    for _, rows in df_user_scores.iterrows():
        user_info_with_id = rows["user_info"].copy()
        user_info_with_id["id"] = rows["user_id"]

        recommendations.append(
            VisitorRecommendation(
                visitor_email=rows["user_email"],
                visitor_details=user_info_with_id,
                score=rows["total_score"]
            )
        )
    
    return recommendations


def recommended_visitors_for_exhibitor(
    event: int,
    exhibitor: int,
    max_count: int,
    exclude: List = [],
    apply_degradation: bool = False
):
    df_exhibitor_category = get_event_exhibitors_with_category(event)
    category_id_list = df_exhibitor_category.loc[df_exhibitor_category["exhibitor_id"] == exhibitor, "category_id"].tolist()

    df_match_weights = get_weight_mapping_to_category(event)
    df_match_weights = df_match_weights[df_match_weights["category_id"].isin(category_id_list)]

    df_buying_scores = get_buying_probability_weight(event)
    df_user_data = get_event_visitors_detail(event, exclude)

    recommendations = get_recommended_visitors(
        df_match_weights,
        df_buying_scores,
        df_user_data,
        max_count,
        apply_degradation
    )

    return VisitorRecommendations(event = event, exhibitor_id = exhibitor, visitors = recommendations)