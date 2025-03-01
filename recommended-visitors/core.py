import os
import math
import json
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from databricks import sql
from typing import List
from schema import VisitorRecommendation, VisitorRecommendations


load_dotenv()


ANSWER_REGION_MAPPING = {
    "5c8a78336d41a10da4f73359": 3490,       # Russia
    "5c8a78336d41a10da4f7335a": 3461,       # CIS
    "5c8a78336d41a10da4f7335b": 3504,       # Europe
    "5c8a78336d41a10da4f7335c": 3476,       # Asia
    "5c8a78336d41a10da4f7335d": 3472,       # North America
    "5c8a78336d41a10da4f7335e": 3473,       # Central & South America
    "5c8a78336d41a10da4f7335f": 3508,       # Middle East
    "5c8a78336d41a10da4f73360": 3483,       # Africa
    "5c8a78336d41a10da4f73351": 3520,       # Australia and the Pacific
}


connection = sql.connect(
    server_hostname = os.environ.get("DATABRICKS_HOST"),
    http_path = os.environ.get("DATABRICKS_HTTP_PATH"),
    access_token = os.environ.get("DATABRICKS_TOKEN"),
)
cursor = connection.cursor()


def get_weight_mapping_to_category(event: int):
    query = f"SELECT category_id, answer, weight FROM dwh.mm.precomputed_mapping_{event}"
    cursor.execute(query)
    match_weights = cursor.fetchall()
    df_match_weights = pd.DataFrame(match_weights, columns=["category_id", "answerId", "weight"])

    return df_match_weights


def get_event_exhibitors_with_category(event: int):
    table_name = f"precomputed_exhibitors_{event}"
    result = cursor.tables(catalog_name="dwh", schema_name="mm", table_name=table_name).fetchall()
    if len(result) == 0:
        raise ValueError("Event Not Found")

    query = f"SELECT ExhibitorID, category_id FROM dwh.mm.precomputed_exhibitors_{event}"
    cursor.execute(query)
    exhibitor_category = cursor.fetchall()
    df_exhibitor_category = pd.DataFrame(exhibitor_category, columns=["exhibitor_id", "category_id"])

    return df_exhibitor_category


def get_buying_probability_weight(event: int):
    query = f"SELECT answer, weight FROM dwh.mm.precomputed_scoring_{event}"
    cursor.execute(query)
    buying_scores = cursor.fetchall()
    df_buying_scores = pd.DataFrame(buying_scores, columns=["answer", "weight"])

    return df_buying_scores


def get_event_visitors_detail(event: int, exclude: List = []):
    query = f"SELECT wisent_user_id, email, user, answer_ids, Region, country FROM dwh.mm.precomputed_visitors_{event}"
    cursor.execute(query)
    user_data = cursor.fetchall()
    df_user_data = pd.DataFrame(user_data, columns=["user_id", "user_email", "user_info", "user_answers", "region", "country"])
    df_user_data = df_user_data[~df_user_data["user_email"].isin(exclude)]

    return df_user_data


def get_subregion_broader_mapping(event_id, region_filter: List[int]):
    query = f"SELECT ItemID, ParentID FROM dwh.mm.precomputed_additional_categories_{event_id}"
    cursor.execute(query)
    region_mapping = cursor.fetchall()
    df_region_mapping = pd.DataFrame(region_mapping, columns=["region_id", "broader_id"])

    available_regions = region_filter.copy()
    for region in region_filter:
        broader_region_id = df_region_mapping.loc[df_region_mapping["region_id"] == region, "broader_id"].iloc[0]
        if broader_region_id == 0:
            continue
        available_regions.append(broader_region_id)
        sub_regions = df_region_mapping.loc[df_region_mapping["broader_id"] == broader_region_id, "region_id"].tolist()
        available_regions = available_regions + sub_regions

    available_regions = list(set(available_regions))
    return available_regions


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
    ).groupby(["user_id", "user_email", "user_info", "country", "region"], as_index=False)["weight"].sum().rename(columns={"weight": "score"})

    df_category_matches_scores = pd.merge(
        df_user_data_exploded,
        df_match_weights,
        left_on="user_answers",
        right_on="answerId",
        how="left"
    ).groupby(["user_id", "user_email", "user_info", "country", "region"], as_index=False)["weight"].sum().rename(columns={"weight": "score"})

    df_user_scores = pd.merge(
        df_match_buying_scores,
        df_category_matches_scores,
        on=["user_id", "user_email", "user_info", "country", "region"],
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

    df_user_scores = df_user_scores.sort_values(by="user_id", ascending=True)
    return df_user_scores


def recommended_visitors_for_exhibitor(
    event: int,
    exhibitor: int,
    max_count: int,
    exclude: List = [],
    apply_degradation: bool = False,
    region_filter: List = []
):
    df_exhibitor_category = get_event_exhibitors_with_category(event)
    category_id_list = df_exhibitor_category.loc[df_exhibitor_category["exhibitor_id"] == exhibitor, "category_id"].tolist()

    if len(category_id_list) == 0:
        raise ValueError("Exhibitor Not Found")

    df_match_weights = get_weight_mapping_to_category(event)
    df_match_weights = df_match_weights[df_match_weights["category_id"].isin(category_id_list)]

    df_buying_scores = get_buying_probability_weight(event)
    df_user_data = get_event_visitors_detail(event, exclude)

    df_user_scores = get_recommended_visitors(
        df_match_weights,
        df_buying_scores,
        df_user_data,
        apply_degradation
    )

    if event == 534 and region_filter:
        available_region = get_subregion_broader_mapping(event, region_filter)
        df_user_answers = df_user_data[["user_id", "user_answers"]]
        df_user_answers["user_answers"] = df_user_answers["user_answers"].apply(list)
        df_user_answers["user_answers"] = df_user_answers["user_answers"].apply(
            lambda x: [ANSWER_REGION_MAPPING.get(answer_id) for answer_id in x]
        )
        df_user_answers = df_user_answers.rename(columns={"user_answers": "region_id"})

        visitors_in_regions = df_user_answers[df_user_answers["region_id"].isin(available_region)]
        visitors_in_regions = list(set(visitors_in_regions["user_id"].tolist()))

        df_visitors_in_region = df_user_scores[df_user_scores["user_id"].isin(visitors_in_regions)]
        df_visitors_out_region = df_user_scores[~df_user_scores["user_id"].isin(visitors_in_regions)]

        df_user_scores = df_visitors_in_region.nlargest(max_count, "total_score")
        count_in_region = len(df_visitors_in_region)
        if max_count > count_in_region:
            df_user_scores = pd.concat([df_user_scores, df_visitors_out_region.nlargest(max_count - count_in_region, "total_score")])
    else:
        df_user_scores = df_user_scores.nlargest(max_count, "total_score")

    df_user_scores["user_info"] = df_user_scores["user_info"].apply(json.loads)

    recommendations = []
    for _, rows in df_user_scores.iterrows():
        user_info_with_id = rows["user_info"].copy()
        user_info_with_id["country"] = rows["country"]
        user_info_with_id["region"] = rows["region"]
        user_info_with_id["id"] = rows["user_id"]

        recommendations.append(
            VisitorRecommendation(
                visitor_email=rows["user_email"],
                visitor_details=user_info_with_id,
                score=rows["total_score"]
            )
        )

    return VisitorRecommendations(event = event, exhibitor_id = exhibitor, visitors = recommendations)