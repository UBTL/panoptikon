import io
import logging
from typing import List, Literal, Optional

import numpy as np
import PIL
import PIL.Image
from pydantic import BaseModel, Field, PrivateAttr
from sqlalchemy import and_, func, literal, literal_column
from sqlalchemy.sql.expression import CTE, select

from inferio.impl.utils import deserialize_array
from panoptikon.db.pql.filters.sortable.sortable_filter import SortableFilter
from panoptikon.db.pql.filters.sortable.text_embeddings import (
    EmbedArgs,
    extract_embeddings,
)
from panoptikon.db.pql.types import (
    OrderTypeNN,
    QueryState,
    get_order_by_field,
    get_order_direction_field,
    get_std_cols,
    get_std_group_by,
)
from panoptikon.db.utils import serialize_f32

logger = logging.getLogger(__name__)


class SourceArgs(BaseModel):
    setter_names: Optional[List[str]] = Field(
        default=None,
        description="The source model names to restrict the search to. These are the models that produced the text.",
    )
    languages: Optional[List[str]] = Field(
        default=None,
        description="The source languages to restrict the search to. These are the languages of the text produced by the source models.",
    )
    min_confidence: float = Field(
        default=0.0,
        description="The minimum confidence of the text as given by its source model",
    )
    min_language_confidence: float = Field(
        default=0.0,
        description="The minimum confidence for language detection in the text",
    )
    min_length: int = Field(
        default=0,
        description="The minimum length of the text in characters",
    )
    confidence_weight: float = Field(
        default=0.0,
        description="""
The weight to apply to the confidence of the source text
on the embedding distance aggregation for individual items with multiple embeddings.
Default is 0.0, which means that the confidence of the source text
does not affect the distance aggregation.
This parameter is only relevant when the source text has a confidence value.
The confidence of the source text is multiplied by the confidence of the other
source text when calculating the distance between two items.
The formula for the distance calculation is as follows:
```
weights = POW((COALESCE(main_source_text.confidence, 1) * COALESCE(other_source_text.confidence, 1)), src_confidence_weight)
distance = SUM(distance * weights) / SUM(weights)
```
So this weight is the exponent to which the confidence is raised, which means that it can be greater than 1.
When confidence weights are set, the distance_aggregation setting is ignored.
""",
    )
    language_confidence_weight: float = Field(
        default=0.0,
        description="""
The weight to apply to the confidence of the source text language
on the embedding distance aggregation.
Default is 0.0, which means that the confidence of the source text language detection
does not affect the distance calculation.
Totally analogous to `src_confidence_weight`, but for the language confidence.
When both are present, the results of the POW() functions for both are multiplied together before being applied to the distance.
```
weights = POW(..., src_confidence_weight) * POW(..., src_language_confidence_weight)
```
""",
    )


class SimilarityArgs(BaseModel):
    target: str = Field(
        ...,
        description="Sha256 hash of the target item to find similar items for",
    )
    setter_name: str = Field(
        ...,
        description="The name of the embedding model used for similarity search",
    )
    distance_function: Literal["L2", "COSINE"] = Field(
        default="L2",
        description="The distance function to use for similarity search. Default is L2.",
    )
    distance_aggregation: Literal["MIN", "MAX", "AVG"] = Field(
        default="AVG",
        description="The method to aggregate distances when an item has multiple embeddings. Default is AVG.",
    )
    src_text: Optional[SourceArgs] = Field(
        default=None,
        description="""
Filters and options to apply on source text.
If not provided, all text embeddings are considered.
The source text is the text which was used to produce the text embeddings.
""",
    )

    clip_xmodal: bool = Field(
        default=False,
        description="""
Whether to use cross-modal similarity for CLIP models.
Default is False. What this means is that the similarity is calculated between image and text embeddings,
rather than just between image embeddings. By default will also use text-to-text similarity.

Note that you must have both image and text embeddings with the same CLIP model for this setting to work.
Text embeddings are derived from text which must have been already previously produced by another model, such as an OCR model or a tagger.
They are generated *separately* from the image embeddings, using a different job (Under 'CLIP Text Embeddings').
Run a batch job with the same clip model for both image and text embeddings to use this setting.
        """,
    )
    xmodal_t2t: bool = Field(
        default=True,
        description="""
When using CLIP cross-modal similarity, whether to use text-to-text similarity as well or just image-to-text and image-to-image.
        """,
    )
    xmodal_i2i: bool = Field(
        default=False,
        description="""
When using CLIP cross-modal similarity, whether to use image-to-image similarity as well or just image-to-text and text-to-text.
        """,
    )


class SimilarTo(SortableFilter):
    order_by: bool = get_order_by_field(True)
    direction: OrderTypeNN = get_order_direction_field("asc")
    similar_to: SimilarityArgs = Field(
        ...,
        title="Item Similarity Search",
        description="""
Search for items similar to a target item using similarity search on embeddings.
The search is based on the image or text embeddings of the provided item.

The count value in the response is equal to the number 
of items returned (+ (page_size - 1) * page for page > 1),
rather than the total number of similar items in the database.
This is because there is no way to define what 
constitutes a "similar" item in a general sense.
We just return the top N items that are most similar to the provided item.
If you still need the total number of "similar" items in the database,
set the `full_count` parameter to true.

The setter name refers to the model that produced the embeddings.
You can find a list of available values for this parameter using the /api/search/stats endpoint.
Any setters of type "text-embedding" or "clip" can be used for this search.

The `limit` parameter can be used to control the number of similar items to return.

"text" embeddings are derived from text produced by another model, such as an OCR model or a tagger.
You can restrict the search to embeddings derived from text that was 
produced by one of a list of specific models by providing the appropriate filter.
You can find a list of available values for text sources using the 
/api/search/stats endpoint, specifically any setter of type "text" will apply.
Remember that tagging models also produce text by concatenating the tags,
 and are therefore also returned as "text" models by the stats endpoint.
Restricting similarity to a tagger model or a set of tagger models
 is recommended for item similarity search based on text embeddings.

""",
    )

    def _validate(self):
        if len(self.similar_to.target.strip()) == 0:
            return self.set_validated(False)

        if len(self.similar_to.setter_name.strip()) == 0:
            return self.set_validated(False)

        return self.set_validated(True)

    def build_query(self, context: CTE, state: QueryState) -> CTE:
        self.raise_if_not_validated()
        from panoptikon.db.pql.tables import (
            embeddings,
            extracted_text,
            item_data,
            items,
            setters,
        )

        args = self.similar_to
        # Join with embeddings and apply filters
        model_name = args.setter_name
        image_embeddings_query = None

        if args.clip_xmodal:
            # If using cross-modal similarity, use the
            # corresponding text embedding setter in the main embeddings query
            model_name = f"t{model_name}"
            # If using cross-modal similarity,
            # The main query only gets the text embeddings
            # We need to get the image embeddings as well
            image_embeddings_query = (
                select(
                    *get_std_cols(context, state),
                )
                .join(
                    item_data,
                    item_data.c.item_id == context.c.item_id,
                )
                .join(
                    setters,
                    (setters.c.id == item_data.c.setter_id)
                    & (setters.c.name == args.setter_name),
                )
                .join(
                    embeddings,
                    item_data.c.id == embeddings.c.id,
                )
            )

        embeddings_query = (
            select(
                *get_std_cols(context, state),
            )
            .join(
                item_data,
                item_data.c.item_id == context.c.item_id,
            )
            .join(
                setters,
                (setters.c.id == item_data.c.setter_id)
                & (setters.c.name == model_name),
            )
            .join(
                embeddings,
                item_data.c.id == embeddings.c.id,
            )
        )

        src_setters = setters.alias("src_setters")
        src_item_data = item_data.alias("src_item_data")

        if args.src_text:
            # Filter text embeddings based on source text
            src_args = args.src_text
            embeddings_query = embeddings_query.join(
                extracted_text,
                extracted_text.c.id == item_data.c.source_id,
            ).join(
                src_item_data,
                src_item_data.c.id == extracted_text.c.id,
            )

            if src_args.setter_names:
                embeddings_query = embeddings_query.join(
                    src_setters,
                    (setters.c.id == item_data.c.setter_id)
                    & (setters.c.name.in_(src_args.setter_names)),
                )

            if src_args.languages:
                embeddings_query = embeddings_query.where(
                    extracted_text.c.language.in_(src_args.languages)
                )

            if src_args.min_confidence > 0:
                embeddings_query = embeddings_query.where(
                    extracted_text.c.confidence >= src_args.min_confidence
                )

            if src_args.min_language_confidence > 0:
                embeddings_query = embeddings_query.where(
                    extracted_text.c.language_confidence
                    >= src_args.min_language_confidence
                )

            if src_args.min_length > 0:
                embeddings_query = embeddings_query.where(
                    extracted_text.c.text_length >= src_args.min_length
                )

        if state.is_count_query:
            # No need to order by distance if we are just counting
            # This basically returns all results that have associated embeddings
            # matching the filters
            if not args.clip_xmodal:
                return self.wrap_query(
                    embeddings_query.group_by(
                        *get_std_group_by(context, state)
                    ),
                    context,
                    state,
                )
            # If using cross-modal similarity, we need to get the image embeddings as well
            assert (
                image_embeddings_query is not None
            ), "Image embeddings query is None"
            # Need to union the text and image embeddings
            union_select_cte = embeddings_query.union(
                image_embeddings_query,
            ).cte(f"union_{self.get_cte_name(state.cte_counter)}")
            # We need to turn this into a select statement
            return self.wrap_query(
                select(union_select_cte).group_by(
                    *get_std_group_by(union_select_cte, state)
                ),
                context,
                state,
            )
        # Group by item_id and emb_id to get all unique embeddings for each unique item
        unqemb_select = (
            embeddings_query.with_only_columns(
                context.c.item_id.label("item_id"),
                items.c.sha256.label("sha256"),
                embeddings.c.id.label("emb_id"),
                embeddings.c.embedding.label("embedding"),
                item_data.c.data_type.label("data_type"),
            )
            .join(
                items,
                items.c.id == context.c.item_id,
            )
            .group_by(
                context.c.item_id,
                embeddings.c.id,
            )
        )
        if args.src_text:
            if args.src_text.confidence_weight != 0:
                unqemb_select = unqemb_select.column(
                    extracted_text.c.confidence.label("confidence")
                )
            if args.src_text.language_confidence_weight != 0:
                unqemb_select = unqemb_select.column(
                    extracted_text.c.language_confidence.label(
                        "language_confidence"
                    )
                )

        unqemb_cte = unqemb_select.cte(
            f"unqemb_{self.get_cte_name(state.cte_counter)}"
        )
        if args.clip_xmodal:
            assert (
                image_embeddings_query is not None
            ), "Image embeddings query is None"
            imgemb_select = (
                image_embeddings_query.with_only_columns(
                    context.c.item_id.label("item_id"),
                    items.c.sha256.label("sha256"),
                    embeddings.c.id.label("emb_id"),
                    embeddings.c.embedding.label("embedding"),
                    item_data.c.data_type.label("data_type"),
                )
                .join(
                    items,
                    items.c.id == context.c.item_id,
                )
                .group_by(
                    context.c.item_id,
                    embeddings.c.id,
                )
            )
            if args.src_text:
                # We need to ensure the columns are the same as the text embeddings
                if args.src_text.confidence_weight != 0:
                    imgemb_select = imgemb_select.column(
                        literal_column("NULL").label("confidence")
                    )
                if args.src_text.language_confidence_weight != 0:
                    imgemb_select = imgemb_select.column(
                        literal_column("NULL").label("language_confidence")
                    )

            imgemb_cte = imgemb_select.cte(
                f"imgemb_{self.get_cte_name(state.cte_counter)}"
            )
            # Now we join the text and image embeddings together
            unqemb_cte = unqemb_cte.union(
                select(
                    *imgemb_cte.columns,
                ).select_from(imgemb_cte),
            )

        # For the target item
        main_embeddings = unqemb_cte.alias("main_embeddings")
        # For the items to compare against
        other_embeddings = unqemb_cte.alias("other_embeddings")

        distance_func = (
            func.vec_distance_L2
            if args.distance_function == "L2"
            else func.vec_distance_cosine
        )
        vec_distance = distance_func(
            main_embeddings.c.embedding,
            other_embeddings.c.embedding,
        )
        if args.distance_aggregation == "MAX":
            rank_column = func.max(vec_distance)
        elif args.distance_aggregation == "AVG":
            rank_column = func.avg(vec_distance)
        elif args.distance_aggregation == "MIN":
            rank_column = func.min(vec_distance)
        else:
            raise ValueError(
                f"Invalid distance aggregation method: {args.distance_aggregation}"
            )

        if args.src_text:
            conf_weight_clause = func.pow(
                func.coalesce(main_embeddings.c.confidence, 1)
                * func.coalesce(other_embeddings.c.confidence, 1),
                args.src_text.confidence_weight,
            )
            lang_conf_weight_clause = func.pow(
                func.coalesce(other_embeddings.c.language_confidence, 1)
                * func.coalesce(main_embeddings.c.language_confidence, 1),
                args.src_text.language_confidence_weight,
            )
            if (
                args.src_text.confidence_weight != 0
                and args.src_text.language_confidence_weight != 0
            ):
                weights = conf_weight_clause * lang_conf_weight_clause
                rank_column = func.sum(vec_distance * weights) / func.sum(
                    weights
                )
            elif args.src_text.confidence_weight != 0:
                rank_column = func.sum(
                    vec_distance * conf_weight_clause
                ) / func.sum(conf_weight_clause)
            elif args.src_text.language_confidence_weight != 0:
                rank_column = func.sum(
                    vec_distance * lang_conf_weight_clause
                ) / func.sum(lang_conf_weight_clause)

        distance_select = (
            select(
                other_embeddings.c.item_id.label("other_item_id"),
                rank_column.label("distance"),
            )
            .select_from(other_embeddings)
            .join(
                main_embeddings,
                main_embeddings.c.sha256 == args.target,
            )
            .where(other_embeddings.c.sha256 != args.target)
            .group_by(other_embeddings.c.item_id)
        )
        if args.clip_xmodal:
            # If using cross-modal similarity, we can restrict the distance calculation
            # to only the relevant types of embeddings
            if not args.xmodal_i2i:
                # Disallow image-to-image similarity
                distance_select = distance_select.where(
                    (main_embeddings.c.data_type != "clip")
                    | (other_embeddings.c.data_type != "clip")
                )
            if not args.xmodal_t2t:
                # Disallow text-to-text similarity
                distance_select = distance_select.where(
                    (main_embeddings.c.data_type != "text-embedding")
                    | (other_embeddings.c.data_type != "text-embedding")
                )

        # Join the target item with all other items
        distance_cte = distance_select.cte(
            f"dist_{self.get_cte_name(state.cte_counter)}"
        )

        # Now we join with the original query to give the min distance for each item
        res = select(
            *get_std_cols(context, state),
            self.derive_rank_column(distance_cte.c.distance),
        ).join(
            distance_cte,
            context.c.item_id == distance_cte.c.other_item_id,
        )
        return self.wrap_query(res, context, state)
