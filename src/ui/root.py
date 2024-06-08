from __future__ import annotations

import os

import gradio as gr

from src.ui.scan import create_scan_UI
from src.ui.toptags import create_toptags_UI
from src.ui.test_model import create_dd_UI
from src.ui.search import create_search_UI
from src.ui.history import create_history_UI
from src.ui.bookmarks import create_bookmarks_UI
from src.ui.components.history_dict import HistoryDict
from src.ui.components.utils import load_bookmarks, save_bookmarks

def create_root_UI():
    with gr.Blocks(css="static/style.css", fill_height=True) as ui:
        select_history = gr.State(value=[])
        bookmarks = gr.State(value=load_bookmarks)
        bookmarks.change(
            fn=save_bookmarks,
            inputs=[bookmarks]
        )

        with gr.Tabs():
            create_search_UI(select_history, bookmarks)
            create_bookmarks_UI(bookmarks)
            create_history_UI(select_history, bookmarks)
            with gr.TabItem(label="Tag Frequency"):
                create_toptags_UI()
            with gr.TabItem(label="File Scan & Tagging"):
                create_scan_UI()
            with gr.TabItem(label="Tagging Model"):
                create_dd_UI()
    ui.launch(share=(os.getenv("GRADIO_SHARE", False) == "true"), server_name=os.getenv("GRADIO_HOSTNAME", None), server_port=os.getenv("GRADIO_PORT", None))