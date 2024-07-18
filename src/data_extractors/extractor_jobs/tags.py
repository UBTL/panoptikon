from __future__ import annotations

import sqlite3
from typing import Dict, List, Sequence, Tuple

import PIL.Image

from src.data_extractors.ai.wd_tagger import Predictor
from src.data_extractors.data_loaders.images import item_image_loader_pillow
from src.data_extractors.extractor_jobs import run_extractor_job
from src.data_extractors.models import TaggerModel
from src.data_extractors.utils import get_threshold_from_env
from src.db import create_tag_setter, get_item_rowid, insert_tag_item
from src.types import ItemWithPath


def combine_results(results: List[dict[str, float]]) -> dict[str, float]:
    """
    Combine multiple results into a single result by picking the highest confidence score for each tag.
    :param results: List of results to combine
    :return: Combined result as a dictionary of tags and scores
    """
    combined_result = dict()
    for result in results:
        for tag, score in result.items():
            if tag not in combined_result or score > combined_result[tag]:
                combined_result[tag] = score
    return combined_result


def aggregate_results(
    results: List[tuple[dict[str, float], dict[str, float], dict[str, float]]]
):
    if len(results) == 1:
        return translate_tags_result(*results[0])
    # Combine all results into a single result for each category
    rating_res, character_res, general_res = zip(*results)
    return translate_tags_result(
        combine_results(list(rating_res)),
        combine_results(list(character_res)),
        combine_results(list(general_res)),
    )


def translate_tags_result(
    rating_res: dict[str, float],
    character_res: dict[str, float],
    general_res: dict[str, float],
):
    # Pick the highest rated tag
    rating, rating_confidence = max(rating_res.items(), key=lambda x: x[1])
    rating_tag = "rating:" + rating
    general_res[rating_tag] = rating_confidence
    return character_res, general_res


def handle_individual_result(
    conn: sqlite3.Connection,
    setter: str,
    item: ItemWithPath,
    results: Sequence[
        Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]
    ],
):
    character_res, general_res = aggregate_results(list(results))
    tags = (
        [
            ("danbooru:character", tag, confidence)
            for tag, confidence in character_res.items()
        ]
        + [
            ("danbooru:general", tag, confidence)
            for tag, confidence in general_res.items()
            if not tag.startswith("rating:")
        ]
        + [
            ("danbooru:rating", tag, confidence)
            for tag, confidence in general_res.items()
            if tag.startswith("rating:")
        ]
    )
    for namespace, tag, confidence in tags:
        tag_rowid = create_tag_setter(
            conn, namespace=namespace, name=tag, setter=setter
        )
        item_rowid = get_item_rowid(conn, item.sha256)
        assert item_rowid is not None
        insert_tag_item(
            conn,
            item_rowid=item_rowid,
            tag_rowid=tag_rowid,
            confidence=confidence,
        )


def run_tag_extractor_job(conn: sqlite3.Connection, model: TaggerModel):
    """
    Run a job that processes items in the database using the given tagging model.
    """
    score_threshold = get_threshold_from_env()
    print(f"Using score threshold {score_threshold}")
    tag_predictor = Predictor(model_repo=model.model_repo())
    tag_predictor.load_model()

    def batch_inference_func(batch_images: Sequence[PIL.Image.Image]):
        return tag_predictor.predict(
            batch_images, general_thresh=score_threshold, character_thresh=None
        )

    def handle_result(
        item: ItemWithPath,
        _: Sequence[PIL.Image.Image],
        outputs: Sequence[
            Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]
        ],
    ):
        handle_individual_result(conn, model.setter_id(), item, outputs)

    return run_extractor_job(
        conn,
        model.setter_id(),
        model.batch_size(),
        item_image_loader_pillow,
        batch_inference_func,
        handle_result,
    )
