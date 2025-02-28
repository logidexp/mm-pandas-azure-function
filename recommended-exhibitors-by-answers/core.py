import os
import math
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


def get_event_exhibitors_with_category(
    event: int,
    exclude: List = []
):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    query = f"SELECT ExhibitorID, category_id FROM dwh.mm.precomputed_exhibitors_{event}"
    cursor.execute(query)
    exhibitor_category = cursor.fetchall()

    df_exhibitor_category = pd.DataFrame(exhibitor_category, columns=["exhibitor_id", "category_id"])
    df_exhibitor_category = df_exhibitor_category[~df_exhibitor_category["exhibitor_id"].isin(exclude)]

    return df_exhibitor_category


def get_subregion_broader_mapping(event_id, region_filter: List[int]):
    connection = connect_to_databricks()
    cursor = connection.cursor()

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


def get_exhibitor_regions(event_id: int):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    query = f"SELECT ExhibitorID, category_id FROM dwh.mm.precomputed_exhibitors_additional_categories_{event_id}"
    cursor.execute(query)
    exhibitor_region = cursor.fetchall()
    df_exhibitor_region = pd.DataFrame(exhibitor_region, columns=["exhibitor_id", "region_id"])

    return df_exhibitor_region


def get_exhibitor_details(event_id: int, exhibitor_list: List[int]):
    connection = connect_to_databricks()
    cursor = connection.cursor()

    # Get exhibitor details
    exhibitor_ids = ", ".join(map(str, exhibitor_list))
    query = f"""
        SELECT * FROM dwh.mm.precomputed_exhibitors_details_{event_id}
        WHERE ExhibitorID IN ({exhibitor_ids})
    """
    cursor.execute(query)
    column_names = [desc[0] for desc in cursor.description]
    exhibitor_details = cursor.fetchall()
    df_exhibitor_details = pd.DataFrame(exhibitor_details, columns=column_names)
    # df_exhibitor_details = df_exhibitor_details.iloc[:, 1:]

    # Get exhibitor additional categories
    query = f"""
        SELECT ExhibitorID, category_id FROM dwh.mm.precomputed_exhibitors_additional_categories_{event_id}
        WHERE ExhibitorID IN ({exhibitor_ids})
    """
    cursor.execute(query)
    additional_category = cursor.fetchall()
    df_additional_category = pd.DataFrame(additional_category, columns=["ExhibitorID", "AdditionalCategories"])
    df_additional_category["AdditionalCategories"] = df_additional_category["AdditionalCategories"].astype(str)
    df_additional_category = df_additional_category.groupby('ExhibitorID')['AdditionalCategories'].agg('|'.join).reset_index()

    df_exhibitor_details = pd.merge(
        df_exhibitor_details,
        df_additional_category,
        on="ExhibitorID",
        how="left"
    )

    # Get exhibitor categories
    query = f"""
        SELECT ExhibitorID, category_id FROM dwh.mm.precomputed_exhibitors_{event_id}
        WHERE ExhibitorID IN ({exhibitor_ids})
    """
    cursor.execute(query)
    exhibitor_category = cursor.fetchall()
    df_exhibitor_category = pd.DataFrame(exhibitor_category, columns=["ExhibitorID", "category_id"])
    
    category_list = list(set(df_exhibitor_category["category_id"].tolist()))
    category_ids = ", ".join(map(str, category_list))
    query = f"""
        SELECT category_id, NameEn, NameRu FROM dwh.mm.precomputed_categories_{event_id}
        WHERE category_id IN ({category_ids})
    """
    cursor.execute(query)
    category_info = cursor.fetchall()
    df_category_info = pd.DataFrame(category_info, columns=["category_id", "NameEn", "NameRu"])
    df_category_info['category_id'] = df_category_info['category_id'].astype('str')

    df_exhibitor_category = pd.merge(
        df_exhibitor_category,
        df_category_info,
        on="category_id",
        how="left"
    )

    df_exhibitor_category = df_exhibitor_category.groupby('ExhibitorID').apply(
        lambda x: x[['NameEn', 'NameRu']].to_dict('records')
    ).reset_index(name='categories')

    df_exhibitor_details = pd.merge(
        df_exhibitor_details,
        df_exhibitor_category,
        on="ExhibitorID",
        how="left"
    )

    return df_exhibitor_details


def recommended_exhibitors_by_answers(
    event: int,
    answers: List[str],
    max_count: int,
    exclude: List = [],
    apply_degradation: bool = False,
    region_filter: List = []
):
    df_answers = pd.DataFrame(answers, columns=["answerId"])
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
        
    if event == 534 and region_filter:
        available_region = get_subregion_broader_mapping(event, region_filter)
        df_exhibitor_region = get_exhibitor_regions(event)

        exhibitors_in_regions = df_exhibitor_region[df_exhibitor_region["region_id"].isin(available_region)]
        exhibitors_in_regions = list(set(exhibitors_in_regions["exhibitor_id"].tolist()))

        df_exhibitor_in_region = df_match_score[df_match_score["exhibitor_id"].isin(exhibitors_in_regions)]
        df_exhibitor_out_region = df_match_score[~df_match_score["exhibitor_id"].isin(exhibitors_in_regions)]

        df_match_score = df_exhibitor_in_region.nlargest(max_count, "score")
        count_in_region = len(df_exhibitor_in_region)
        if max_count > count_in_region:
            df_match_score = pd.concat([df_match_score, df_exhibitor_out_region.nlargest(max_count - count_in_region, "score")])
    else:
        df_match_score = df_match_score.nlargest(max_count, "score")

    final_exhibitors = df_match_score["exhibitor_id"].tolist()
    exhibitor_details = get_exhibitor_details(event, final_exhibitors)
    exhibitor_details["region_filter"] = "|".join([str(region) for region in region_filter])
    exhibitor_details = exhibitor_details.to_dict("records")

    recommendations = []
    index = 0
    for _, row in df_match_score.iterrows():
        recommendations.append(
            ExhibitorRecommendation(
                exhibitor_id = row["exhibitor_id"],
                exhibitor_details = exhibitor_details[index],
                score = row["score"]
            )
        )
        index += 1

    return ExhibitorRecommendations(event = event, visitor_email = "", exhibitors = recommendations)