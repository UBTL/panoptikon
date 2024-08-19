from __future__ import annotations

import logging
from dataclasses import dataclass

import gradio as gr

from panoptikon.ui.components.utils import get_all_bookmark_folders

logger = logging.getLogger(__name__)


def on_bookmark_folder_change(bookmarks_namespace: str):
    logger.debug(f"Bookmark namespace changed to {bookmarks_namespace}")
    return bookmarks_namespace


def on_input(namespace_chosen: str, bookmarks_namespace: str):
    logger.debug(f"Previous namespace {bookmarks_namespace}")
    logger.debug(f"Input namespace {namespace_chosen}")
    new_value = (
        namespace_chosen
        if len(namespace_chosen.strip()) > 0
        else bookmarks_namespace
    )
    logger.debug(f"New namespace {new_value}")
    return new_value, new_value


def on_tab_load():
    return gr.update(choices=get_all_bookmark_folders())


@dataclass
class BookmarkFolderChooser:
    bookmark_folder_choice: gr.Dropdown


def create_bookmark_folder_chooser(
    parent_tab: gr.TabItem | None = None,
    bookmarks_namespace: gr.State | None = None,
):
    bookmark_folder_choice = gr.Dropdown(
        choices=[(c, c) for c in get_all_bookmark_folders()],
        value="default",
        allow_custom_value=True,
        visible=bookmarks_namespace != None,
        label="Bookmark group name",
        scale=1,
    )

    if parent_tab is not None:
        parent_tab.select(fn=on_tab_load, outputs=[bookmark_folder_choice])

    if bookmarks_namespace is not None:
        bookmarks_namespace.change(
            fn=on_bookmark_folder_change,
            inputs=[bookmarks_namespace],
            outputs=[bookmark_folder_choice],
        )

    bookmark_folder_choice.input(
        fn=on_input,
        inputs=[bookmark_folder_choice, bookmarks_namespace],
        outputs=[bookmark_folder_choice, bookmarks_namespace],
    )

    return BookmarkFolderChooser(bookmark_folder_choice=bookmark_folder_choice)