import base64
import io
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic.dataclasses import dataclass

from inferio.impl.utils import deserialize_array
from panoptikon.api.routers.utils import get_db_readonly
from panoptikon.db import get_database_connection
from panoptikon.db.bookmarks import get_all_bookmark_namespaces
from panoptikon.db.embeddings import find_similar_items
from panoptikon.db.extracted_text import get_text_stats
from panoptikon.db.extraction_log import get_existing_setters
from panoptikon.db.files import get_all_mime_types, get_file_stats
from panoptikon.db.folders import get_folders_from_database
from panoptikon.db.search import search_files
from panoptikon.db.search.types import SearchQuery
from panoptikon.db.search.utils import pprint_dataclass
from panoptikon.db.tags import find_tags, get_all_tag_namespaces
from panoptikon.db.tagstats import (
    get_min_tag_confidence,
    get_most_common_tags_frequency,
)
from panoptikon.db.utils import serialize_f32
from panoptikon.types import (
    ExtractedTextStats,
    FileSearchResult,
    OutputDataType,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/search",
    tags=["search"],
    responses={404: {"description": "Not found"}},
)


@dataclass
class FileSearchResultModel:
    count: int
    results: List[FileSearchResult]


def process_results(
    results: List[Tuple[FileSearchResult, int]]
) -> FileSearchResultModel:
    if len(results) == 0:
        return FileSearchResultModel(count=0, results=[])
    return FileSearchResultModel(
        count=results[0][1], results=[r[0] for r in results]
    )


def deserialize_array(buffer: bytes) -> np.ndarray:
    bio = io.BytesIO(buffer)
    bio.seek(0)
    return np.load(bio, allow_pickle=False)


def extract_embeddings(buffer: bytes) -> bytes:
    numpy_array = deserialize_array(base64.b64decode(buffer))
    assert isinstance(
        numpy_array, np.ndarray
    ), "Expected a numpy array for embeddings"
    # Check the number of dimensions
    if len(numpy_array.shape) == 1:
        # If it is a 1D array, it is a single embedding
        return serialize_f32(numpy_array.tolist())
    # If it is a 2D array, it is a list of embeddings, get the first one
    return serialize_f32(numpy_array[0].tolist())


@router.post(
    "",
    summary="Search for files in the database",
    description="""
Search for files in the database based on the provided query parameters.

The search query takes a `SearchQuery` object as input, which contains all the parameters supported by search.
Search operates on `files`, which means that results are not unique by `sha256` value.
The `count` returned in the response is the total number of unique files that match the query.
There could be zero results even if the `count` is higher than zero,
if the `page` parameter is set beyond the number of pages available.

For semantic search, embeddings should be provided as base64-encoded byte strings in npy format.
To get the correct embeddings, use the /api/inference/predict endpoint with the correct inference_id.

It will return an application/octet-stream response with the embeddings in the correct format, which can be base64-encoded and used in the search query.

To get the list of embedding models the data is indexed with, use /api/search/stats and look for setters with "text-embedding" or "clip" type.
    """,
    response_model=FileSearchResultModel,
)
def search(
    search_query: SearchQuery = Body(
        default_factory=lambda: SearchQuery(),
        description="The search query to execute",
    ),
    conn_args: Dict[str, Any] = Depends(get_db_readonly),
):
    conn = get_database_connection(**conn_args)
    try:
        logger.debug(
            f"Searching for files with query: {pprint_dataclass(search_query)}"
        )
        if search_query.query.filters.image_embeddings:
            query = search_query.query.filters.image_embeddings.query
            search_query.query.filters.image_embeddings.query = (
                extract_embeddings(query)
            )
        if search_query.query.filters.extracted_text_embeddings:
            query = search_query.query.filters.extracted_text_embeddings.query
            search_query.query.filters.extracted_text_embeddings.query = (
                extract_embeddings(query)
            )
        results = list(search_files(conn, search_query))
        return process_results(results)
    finally:
        conn.close()


@dataclass
class TagStats:
    namespaces: List[str]
    min_confidence: float


@dataclass
class FileStats:
    total: int
    unique: int
    mime_types: List[str]


@dataclass
class APISearchStats:
    setters: List[Tuple[OutputDataType, str]]
    bookmarks: List[str]
    files: FileStats
    tags: TagStats
    folders: List[str]
    text_stats: ExtractedTextStats


@router.get(
    "/stats",
    summary="Get statistics on the searchable data",
    description="""
Get statistics on the data indexed in the database.
This includes information about the tag namespaces, bookmark namespaces, file types, and folders present.
Most importantly, it includes the list of currently existing setters for each data type.
This information is relevant for building search queries.
    """,
    response_model=APISearchStats,
)
def get_stats(
    conn_args: Dict[str, Any] = Depends(get_db_readonly),
    user: str = Query(
        "user",
        description="The bookmarks user to get the bookmark namespaces for",
    ),
    include_wildcard: bool = Query(
        True,
        description="Include namespaces from bookmarks with the * user value",
    ),
):
    conn = get_database_connection(**conn_args)
    try:
        setters = get_existing_setters(conn)
        bookmark_namespaces = get_all_bookmark_namespaces(
            conn, include_wildcard=include_wildcard, user=user
        )
        file_types = get_all_mime_types(conn)
        tag_namespaces = get_all_tag_namespaces(conn)
        folders = get_folders_from_database(conn)
        min_tags_threshold = get_min_tag_confidence(conn)
        text_stats = get_text_stats(conn)
        files, items = get_file_stats(conn)
        return APISearchStats(
            setters=setters,
            bookmarks=bookmark_namespaces,
            files=FileStats(total=files, unique=items, mime_types=file_types),
            tags=TagStats(
                namespaces=tag_namespaces, min_confidence=min_tags_threshold
            ),
            folders=folders,
            text_stats=text_stats,
        )
    finally:
        conn.close()


@dataclass
class TagFrequency:
    tags: List[Tuple[str, str, int, float]]


@router.get(
    "/tags/top",
    summary="Get the most common tags in the database",
    description="""
Get the most common tags in the database, based on the provided query parameters.
The result is a list of tuples, where each tuple contains the namespace, tag name, 
occurrences count, and relative frequency % (occurrences / total item_setter pairs).
The latter value is expressed as a float between 0 and 1.
The tags are returned in descending order of frequency.
The `limit` parameter can be used to control the number of tags to return.
The `namespace` parameter can be used to restrict the search to a specific tag namespace.
The `setters` parameter can be used to restrict the search to specific setters.
The `confidence_threshold` parameter can be used to filter tags based on the minimum confidence threshold.
    """,
    response_model=TagFrequency,
)
def get_top_tags(
    conn_args: Dict[str, Any] = Depends(get_db_readonly),
    namespace: Optional[str] = Query(
        None, description="The tag namespace to search in"
    ),
    setters: List[str] = Query(
        [],
        description="The tag setter names to restrict the search to. Default is all",
    ),
    confidence_threshold: Optional[float] = Query(
        None,
        ge=0.0,
        le=1.0,
        description="The minimum confidence threshold for tags",
    ),
    limit: int = Query(10),
):
    conn = get_database_connection(**conn_args)
    try:
        return TagFrequency(
            tags=get_most_common_tags_frequency(
                conn,
                namespace=namespace,
                setters=setters,
                confidence_threshold=confidence_threshold,
                limit=limit,
            )
        )
    finally:
        conn.close()


@dataclass
class TagSearchResults:
    tags: List[Tuple[str, str, int]]


@router.get(
    "/tags",
    summary="Search tag names for autocompletion",
    description="""
Given a string, finds tags whose names contain the string.
Meant to be used for autocompletion in the search bar.
The `limit` parameter can be used to control the number of tags to return.
Returns a list of tuples, where each tuple contains the namespace, name, 
and the number of unique items tagged with the tag.
The tags are returned in descending order of the number of items tagged.
    """,
    response_model=TagSearchResults,
)
def get_tags(
    name: str = Query(..., description="The (partial) tag name to search for"),
    limit: int = Query(10),
    conn_args: Dict[str, Any] = Depends(get_db_readonly),
):
    conn = get_database_connection(**conn_args)
    try:
        tags = find_tags(conn, name, limit)
        tags.sort(key=lambda x: x[2], reverse=True)
        return TagSearchResults(tags)
    finally:
        conn.close()


@router.get(
    "/similar/{sha256}/{setter_name:path}",
    summary="Find similar items in the database",
    description="""
Find similar items in the database based on the provided SHA256 and setter name.
The search is based on the image or text embeddings of the provided item.

The count value in the response is equal to the number of items returned, rather than the total number of similar items in the database.
This is because there is no way to define what constitutes a "similar" item in a general sense. We just return the top N items that are most similar to the provided item.

The setter name refers to the model that produced the embeddings.
You can find a list of available values for this parameter using the /api/search/stats endpoint.
Any setters of type "text-embedding" or "clip" can be used for this search.

The `limit` parameter can be used to control the number of similar items to return.

"text" embeddings are derived from text produced by another model, such as an OCR model or a tagger.
You can restrict the search to embeddings derived from text that was produced by one of a list of specific models by providing the `src_setter_names` parameter.
You can find a list of available values for this parameter using the /api/search/stats endpoint, specifically any setter of type "text" will work.
Remember that tagging models also produce text by concatenating the tags, and are therefore also returned as "text" models by the stats endpoint.
Restricting similarity to a tagger model or a set of tagger models is recommended for item similarity search based on text embeddings.
    """,
    response_model=FileSearchResultModel,
)
def find_similar(
    sha256: str,
    setter_name: str = Path(
        ...,
        description="The name of the embedding model use for similarity search",
    ),
    src_setter_names: Optional[List[str]] = Query(
        None,
        description="The source model names to restrict the search to. These are the models that produced the text for the items from which the text embeddings were produced.",
    ),
    src_languages: Optional[List[str]] = Query(
        None,
        description="The source languages to restrict the search to. These are the languages of the text produced by the source models.",
    ),
    src_text_min_length: int = Query(
        0,
        description="The minimum length of the text produced by the source models to consider for similarity search",
    ),
    src_min_confidence: float = Query(
        0.0,
        description="The minimum confidence of the text produced by the source models to consider for similarity search",
    ),
    src_min_language_confidence: float = Query(
        0.0,
        description="The minimum language confidence of the text produced by the source models to consider for similarity search",
    ),
    clip_cross_modal: bool = Query(
        False,
        description="""
Whether to use cross-modal similarity for CLIP models.
Default is False. What this means is that the similarity is calculated between the image and text embeddings,
rather than just the image embeddings, as well as between the text embeddings and the image embeddings.
Note that you must have both image and text embeddings with the same CLIP model for this to work.
Text embeddings are derived from text produced by another model, such as an OCR model or a tagger.
They are generated *separately* from the image embeddings, using a different job (Under 'CLIP Text Embeddings').
            """,
    ),
    cross_modal_text_to_text: bool = Query(
        True,
        description="""
When using CLIP cross-modal similarity, whether to use text-to-text similarity as well or just image-to-text and image-to-image.
""",
    ),
    cross_modal_image_to_image: bool = Query(
        False,
        description="""
When using CLIP cross-modal similarity, whether to use image-to-image similarity as well or just image-to-text and text-to-text.
""",
    ),
    limit: int = Query(10),
    conn_args: Dict[str, Any] = Depends(get_db_readonly),
):
    conn = get_database_connection(**conn_args)
    start_time = time.time()
    try:
        results = list(
            find_similar_items(
                conn,
                sha256,
                setter_name,
                src_setter_names,
                src_languages,
                src_text_min_length,
                src_min_confidence,
                src_min_language_confidence,
                clip_cross_modal_compare=clip_cross_modal,
                clip_cross_modal_compare_text_to_text=cross_modal_text_to_text,
                clip_cross_modal_compare_image_to_image=cross_modal_image_to_image,
                limit=limit,
            )
        )
        logger.debug(
            f"Found {len(results)} similar items in {time.time() - start_time:.2f}s"
        )
        return FileSearchResultModel(count=len(results), results=results)
    finally:
        conn.close()
