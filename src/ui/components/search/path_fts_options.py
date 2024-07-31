from dataclasses import asdict
from typing import Any, List, Tuple

import gradio as gr
from gradio.components import Component

from src.db.search.types import PathTextFilter, SearchQuery
from src.db.search.utils import from_dict
from src.ui.components.search.utils import bind_event_listeners


def create_path_fts_opts(query_state: gr.State, search_stats_state: gr.State):
    with gr.Tab(label="MATCH Filename/Path"):
        elements = []
        with gr.Row():
            path_search = gr.Textbox(
                key="path_search",
                label="MATCH query on filename or path",
                show_copy_button=True,
                scale=2,
            )
            elements.append(path_search)
            search_path_in = gr.Radio(
                key="search_path_in",
                choices=[
                    ("Full Path", "full_path"),
                    ("Filename", "filename"),
                ],
                interactive=True,
                label="Match",
                value="full_path",
                scale=1,
            )
            elements.append(search_path_in)

    def on_change_data(query: SearchQuery, args: dict[Component, Any]):
        path_search_val: str = args[path_search]
        search_path_in_val: str = args[search_path_in]
        only_match_filename = search_path_in_val == "filename"
        if path_search_val:
            query.query.filters.path = PathTextFilter(
                query=path_search_val, only_match_filename=only_match_filename
            )
        else:
            query.query.filters.path = None

        return query

    bind_event_listeners(
        query_state,
        search_stats_state,
        elements,
        on_change_data,
    )
    return elements, on_change_data
