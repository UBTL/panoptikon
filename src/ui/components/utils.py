from __future__ import annotations

import gradio as gr

from src.db import add_bookmark, remove_bookmark, delete_bookmarks_exclude_last_n, get_database_connection, get_all_bookmark_namespaces, get_bookmark_metadata, get_bookmarks

def toggle_bookmark(bookmarks_namespace: str, selected_image_sha256: str, button_name: str):
    conn = get_database_connection()
    if button_name == "Bookmark":
        add_bookmark(conn, namespace=bookmarks_namespace, sha256=selected_image_sha256)
        print(f"Added bookmark")
    else:
        remove_bookmark(conn, namespace=bookmarks_namespace, sha256=selected_image_sha256)
        print(f"Removed bookmark")
    conn.commit()
    conn.close()
    return on_selected_image_get_bookmark_state(bookmarks_namespace=bookmarks_namespace, sha256=selected_image_sha256)

def on_selected_image_get_bookmark_state(bookmarks_namespace: str, sha256: str):
    conn = get_database_connection()
    is_bookmarked, _ = get_bookmark_metadata(conn, namespace=bookmarks_namespace, sha256=sha256)
    conn.commit()
    conn.close()
    # If the image is bookmarked, we want to show the "Remove Bookmark" button
    return gr.update(value="Remove Bookmark" if is_bookmarked else "Bookmark")

def get_all_bookmark_folders():
    conn = get_database_connection()
    bookmark_folders = get_all_bookmark_namespaces(conn)
    conn.close()
    return bookmark_folders

def get_all_bookmarks_in_folder(bookmarks_namespace: str, page_size: int = 1000, page: int = 1):
    conn = get_database_connection()
    bookmarks, total_bookmarks = get_bookmarks(conn, namespace=bookmarks_namespace, page_size=page_size, page=page)
    conn.close()
    return bookmarks, total_bookmarks

def delete_bookmarks_except_last_n(bookmarks_namespace: str, keep_last_n: int):
    conn = get_database_connection()
    delete_bookmarks_exclude_last_n(conn, namespace=bookmarks_namespace, n=keep_last_n)
    conn.commit()
    conn.close()

def delete_bookmark(bookmarks_namespace: str, sha256: str):
    conn = get_database_connection()
    remove_bookmark(conn, namespace=bookmarks_namespace, sha256=sha256)
    conn.commit()
    conn.close()