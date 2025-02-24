import os
import math
import json
import pandas as pd
from dotenv import load_dotenv
from databricks import sql
from typing import List
from schema import ExhibitorRecommendation, ExhibitorRecommendations


load_dotenv()


def connect_to_databricks():
    connection = sql.connect(
        server_hostname = os.environ.get("DATABRICKS_HOST"),
        http_path = os.environ.get("DATABRICKS_HTTP_PATH"),
        access_token = os.environ.get("DATABRICKS_TOKEN"),
    )
    return connection


def get_answer_id_list_by_email(event: int, email: str):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    query = f"SELECT answer_ids FROM dwh.mm.precomputed_visitors_{event} WHERE email = '{email}'"
    cursor.execute(query)
    answers = cursor.fetchall()[0][0]
    df_answers = pd.DataFrame({"answerId": answers})

    return df_answers


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


def recommended_exhibitors_for_visitor_email(
    event: int,
    email: str,
    max_count: int,
    exclude: List = [],
    apply_degradation: bool = False
):
    df_answers = get_answer_id_list_by_email(event, email)
    df_match_weights = get_weight_mapping_to_category(event)
    df_exhibitor_category = get_event_exhibitors_with_category(event, exclude)

    df_match_answer_weight = pd.merge(
        df_answers,
        df_match_weights,
        on=["answerId"],
        how="inner"
    )[["category_id", "answerId", "weight"]]

    df_match_exhibitor_weight = pd.merge(
        df_exhibitor_category,
        df_match_answer_weight,
        on=["category_id"],
        how="inner"
    )

    df_match_score = (
        df_match_exhibitor_weight.groupby("exhibitor_id", as_index=False)["weight"]
            .sum()
            .sort_values(by="exhibitor_id", ascending=True)
            .rename(columns={"weight": "score"})
    )

    if apply_degradation:
        df_exhibitor_category_count = (
            df_exhibitor_category.groupby("exhibitor_id", as_index=False)["category_id"]
            .count()
            .rename(columns={"category_id": "category_count"})
        )
        df_match_score = pd.merge(
            df_match_score,
            df_exhibitor_category_count,
            on="exhibitor_id",
            how="left"
        )
        df_match_score["score"] = df_match_score["score"] / (1 + df_match_score["category_count"].apply(math.log))
    
    df_match_score = df_match_score.nlargest(max_count, "score")

    recommendations = []
    for _, row in df_match_score.iterrows():
        recommendations.append(
            ExhibitorRecommendation(
                exhibitor_id = row["exhibitor_id"],
                exhibitor_details = {},
                score = row["score"]
            )
        )

    return ExhibitorRecommendations(event = event, visitor_email = email, exhibitors = recommendations)