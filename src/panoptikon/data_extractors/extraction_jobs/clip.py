import sqlite3
from typing import Sequence

import numpy as np

from panoptikon.data_extractors.ai.clip import CLIPEmbedder
from panoptikon.data_extractors.data_loaders.images import (
    item_image_loader_numpy,
)
from panoptikon.data_extractors.extraction_jobs import run_extraction_job
from panoptikon.data_extractors.models import ImageEmbeddingModel
from panoptikon.db.image_embeddings import insert_image_embedding
from panoptikon.types import ItemWithPath


def run_image_embedding_extractor_job(
    conn: sqlite3.Connection, model_opt: ImageEmbeddingModel
):
    batch_size = model_opt.get_group_batch_size(conn)
    embedder = CLIPEmbedder(
        model_name=model_opt.clip_model_name(),
        pretrained=model_opt.clip_model_checkpoint(),
        batch_size=batch_size,
    )
    embedder.load_model()

    def load_images(item: ItemWithPath):
        return item_image_loader_numpy(conn, item)

    def process_batch(batch: Sequence[np.ndarray]):
        return embedder.get_image_embeddings(batch)

    def handle_item_result(
        log_id: int,
        item: ItemWithPath,
        inputs: Sequence[np.ndarray],
        embeddings: Sequence[np.ndarray],
    ):
        embeddings_list = [embedding.tolist() for embedding in embeddings]
        for embedding in embeddings_list:
            insert_image_embedding(conn, item.sha256, log_id, embedding)

    def cleanup():
        embedder.unload_model()

    return run_extraction_job(
        conn,
        model_opt,
        load_images,
        process_batch,
        handle_item_result,
        cleanup,
    )