from __future__ import annotations

from calendar import c
from datetime import datetime
from typing import List, Type

import gradio as gr

import src.data_extractors.models as models
from src.data_extractors.utils import get_chromadb_client
from src.db import (
    delete_tags_from_setter,
    get_all_file_scans,
    get_all_tag_scans,
    get_database_connection,
    get_folders_from_database,
    vacuum_database,
)
from src.folders import rescan_all_folders, update_folder_lists


def get_folders():
    conn = get_database_connection()
    folders = get_folders_from_database(conn)
    conn.close()
    return "\n".join(folders)


def get_excluded_folders():
    conn = get_database_connection()
    folders = get_folders_from_database(conn, included=False)
    conn.close()
    return "\n".join(folders)


def parse_iso_date(date: str):
    return datetime.fromisoformat(date).strftime("%Y-%m-%d %H:%M:%S")


def isodate_to_epoch(date: str):
    return int(datetime.fromisoformat(date).timestamp())


def isodate_minutes_diff(date1: str, date2: str):
    a, b = datetime.fromisoformat(date1), datetime.fromisoformat(date2)
    return round(
        ((a - b).total_seconds() / 60),
        2,
    )


def update_folders(
    included_folders_text: str,
    excluded_folders_text: str,
    delete_unavailable_files: bool = True,
):
    new_included_folders = (
        [p for p in included_folders_text.strip().split("\n")]
        if len(included_folders_text.strip()) > 0
        else []
    )
    new_excluded_folders = (
        [p for p in excluded_folders_text.strip().split("\n")]
        if len(excluded_folders_text.strip()) > 0
        else []
    )
    conn = get_database_connection()
    try:
        cursor = conn.cursor()
        # Begin a transaction
        cursor.execute("BEGIN")
        update_result = update_folder_lists(
            conn,
            new_included_folders,
            new_excluded_folders,
            delete_unavailable_files,
        )
        update_result_text = f"""
        Removed {update_result.included_deleted} included folders, {update_result.excluded_deleted} excluded folders;
        Included folders added (and scanned): {", ".join(update_result.included_added)} ({len(update_result.scan_ids)});
        Excluded folders added: {", ".join(update_result.excluded_added)};
        Removed {update_result.unavailable_files_deleted} files from the database which were no longer available on the filesystem {"(enabled)" if delete_unavailable_files else "(disabled)"};
        Removed {update_result.excluded_folder_files_deleted} files from the database that were inside excluded folders;
        Removed {update_result.orphan_files_deleted} files from the database that were no longer inside included folders;
        Removed {update_result.orphan_items_deleted} orphaned items (with no corresponding files) from the database. Any bookmarks on these items were also removed.
        """
        conn.commit()
        vacuum_database(conn)
    except Exception as e:
        # Rollback the transaction on error
        conn.rollback()
        conn.close()
        return f"Error: {e}", included_folders_text, excluded_folders_text

    current_included_folders = get_folders_from_database(conn, included=True)
    current_excluded_folders = get_folders_from_database(conn, included=False)
    conn.close()

    return (
        f"{update_result_text}",
        "\n".join(current_included_folders),
        "\n".join(current_excluded_folders),
        fetch_scan_history(),
        fetch_tagging_history(),
    )


def rescan_folders(delete_unavailable_files: bool = True):
    conn = get_database_connection()
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    ids, files_deleted, items_deleted = rescan_all_folders(
        conn, delete_unavailable=delete_unavailable_files
    )
    conn.commit()
    vacuum_database(conn)
    conn.close()
    return (
        f"Rescanned all folders. Removed {files_deleted} files and {items_deleted} orphaned items.",
        fetch_scan_history(),
        fetch_tagging_history(),
    )


def run_model_job(model_opt: models.ModelOpts):
    print(f"Running job for model {model_opt}")
    conn = get_database_connection()
    cdb = get_chromadb_client()
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    images, videos, failed = model_opt.run_extractor(conn, cdb)
    conn.commit()
    vacuum_database(conn)
    failed_str = "\n".join(failed)
    report_str = f"""
    Extraction completed for model {model_opt}.
    Successfully processed {images} images and {videos} videos.
    {len(failed)} files failed to process due to errors.
    Failed files:
    {failed_str}
    """
    conn.close()
    return report_str


def delete_model_data(model_opt: models.ModelOpts):
    print(f"Running data deletion job for model {model_opt}")
    conn = get_database_connection()
    cdb = get_chromadb_client()
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    report_str = model_opt.delete_extracted_data(conn, cdb)
    conn.commit()
    vacuum_database(conn)
    conn.close()
    return report_str


def regenerate_tags(
    tag_models: List[str] = [models.TagsModel.default_model()],
):
    print(f"Regenerating tags for models: {tag_models}")
    full_report = ""
    for model in tag_models:
        model_opt = models.TagsModel(model_name=model)
        report_str = run_model_job(model_opt)
        full_report += report_str
    return full_report, fetch_scan_history(), fetch_tagging_history()


def generate_embeds():
    report_str = run_model_job(models.ImageEmbeddingModel())
    return report_str, fetch_scan_history(), fetch_tagging_history()


def run_ocr():
    report_str = run_model_job(models.OCRModel())
    return report_str, fetch_scan_history(), fetch_tagging_history()


def run_whisper():
    report_str = run_model_job(models.WhisperSTTModel())
    return report_str, fetch_scan_history(), fetch_tagging_history()


def delete_tags(tag_models: List[str] = []):
    conn = get_database_connection()
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    message = ""
    for model in tag_models:
        tags_removed, items_tags_removed = delete_tags_from_setter(conn, model)
        message += f"Removed {tags_removed} tags from {items_tags_removed} items tagged by model {model}.\n"
    conn.commit()
    vacuum_database(conn)
    conn.close()
    return message, fetch_scan_history(), fetch_tagging_history()


def fetch_scan_history():
    conn = get_database_connection()
    file_scans = get_all_file_scans(conn)
    conn.close()
    file_scans = [
        [
            f.id,
            parse_iso_date(f.start_time),
            parse_iso_date(f.end_time),
            isodate_minutes_diff(f.end_time, f.start_time),
            f.path,
            f.total_available,
            f.marked_unavailable,
            f.errors,
            f.new_items,
            f.new_files,
            f.unchanged_files,
            f.modified_files,
        ]
        for f in file_scans
    ]

    return gr.Dataset(samples=file_scans)


def fetch_tagging_history():
    conn = get_database_connection()
    tag_scans = get_all_tag_scans(conn)
    conn.close()
    tag_scans = [
        [
            t.id,
            parse_iso_date(t.start_time),
            parse_iso_date(t.end_time),
            isodate_minutes_diff(t.end_time, t.start_time),
            t.setter,
            t.threshold,
            t.image_files,
            t.video_files,
            t.other_files,
            t.video_frames,
            t.total_frames,
            t.errors,
            t.timeouts,
            t.total_remaining,
        ]
        for t in tag_scans
    ]
    return gr.Dataset(samples=tag_scans)


def fetch_all_history():
    return fetch_scan_history(), fetch_tagging_history()


def create_scan_dataset(samples=[]):
    print(samples)
    scan_history = gr.Dataset(
        label="File Scan History",
        type="index",
        samples_per_page=25,
        samples=samples,
        headers=[
            "ID",
            "Start Time",
            "End Time",
            "Duration (m)",
            "Path",
            "Total Available",
            "Marked Unavailable",
            "Errors",
            "New Items",
            "New Files",
            "Unchanged Files",
            "Modified Files",
        ],
        components=[
            "number",
            "textbox",
            "textbox",
            "number",
            "textbox",
            "number",
            "number",
            "number",
            "number",
            "number",
            "number",
            "number",
        ],
        scale=1,
    )
    return scan_history


def create_job_dataset(samples=[]):
    tagging_history = gr.Dataset(
        label="Tagging History",
        type="index",
        samples_per_page=25,
        samples=samples,
        headers=[
            "ID",
            "Start Time",
            "End Time",
            "Duration (m)",
            "Tag Model",
            "Threshold",
            "Image Files",
            "Video Files",
            "Other Files",
            "Video Frames",
            "Total Frames",
            "Errors",
            "Timeouts",
            "Remaining Untagged",
        ],
        components=[
            "number",
            "textbox",
            "textbox",
            "number",
            "textbox",
            "number",
            "number",
            "number",
            "number",
            "number",
            "number",
            "number",
            "number",
            "number",
        ],
        scale=1,
    )
    return tagging_history


def extractor_job_UI(
    model_type: Type[models.ModelOpts],
    report_state: gr.State,
):
    def run_job(batch: int, chosen_model: List[str]):
        report_string = ""
        for model_name in chosen_model:
            extractor_model = model_type(
                batch_size=batch, model_name=model_name
            )
            report_string += run_model_job(extractor_model)
        return report_string

    def delete_data(chosen_model: List[str]):
        report_string = ""
        for model_name in chosen_model:
            extractor_model = model_type(model_name=model_name)
            report_string += delete_model_data(extractor_model)
        return report_string

    with gr.TabItem(label=model_type.name()) as extractor_tab:
        gr.Markdown(
            f"""
            ## {model_type.name()} Extraction Job
            ### {model_type.description()}

            This will run the {model_type.name()} extractor on the database.
            The extractor will process all items in the database that have not been processed by the selected model yet.
            Data will be extracted from the items and indexed in the database for search and retrieval.
            """
        )
        with gr.Row():
            with gr.Group():
                model_choice = gr.Dropdown(
                    label="Model(s) to Use",
                    multiselect=True,
                    value=[
                        model_type.default_model(),
                    ],
                    choices=[
                        (name, name) for name in model_type.available_models()
                    ],
                )
                batch_size = gr.Slider(
                    label="Batch Size",
                    minimum=1,
                    maximum=128,
                    value=model_type.default_batch_size(),
                )
        with gr.Row():
            run_button = gr.Button("Run Batch Job")
            delete_button = gr.Button(
                "Delete All Data Extracted by Selected Model(s)"
            )

    run_button.click(
        fn=run_job,
        inputs=[batch_size, model_choice],
        outputs=[report_state],
    )
    delete_button.click(
        fn=delete_data,
        inputs=[model_choice],
        outputs=[report_state],
    )


def create_extractor_UI(
    report_state: gr.State,
):
    with gr.Row():
        with gr.Tabs():
            extractor_job_UI(models.TagsModel, report_state)
            extractor_job_UI(models.OCRModel, report_state)
            extractor_job_UI(models.WhisperSTTModel, report_state)
            extractor_job_UI(models.ImageEmbeddingModel, report_state)


def report_state_change(report_state: str):
    return report_state, fetch_scan_history(), fetch_tagging_history()


def create_scan_UI():
    report_state = gr.State(value="")
    with gr.TabItem(label="File Scan & Tagging") as scan_tab:
        with gr.Column(elem_classes="centered-content", scale=0):
            with gr.Row():
                included_directory_list = gr.Textbox(
                    label="Include Directories",
                    value=get_folders,
                    lines=20,
                    interactive=True,
                )
                excluded_directory_list = gr.Textbox(
                    label="Exclude Directories",
                    value=get_excluded_folders,
                    lines=20,
                    interactive=True,
                )
            with gr.Row():
                with gr.Column():
                    with gr.Row():
                        delete_unavailable_files = gr.Checkbox(
                            label="Remove files from the database if they are no longer found on the filesystem",
                            value=True,
                            interactive=True,
                        )
                    with gr.Row():
                        update_button = gr.Button(
                            "Update Directory Lists and Scan New Entries"
                        )
                        scan_button = gr.Button("Rescan all Directories")
                with gr.Column():
                    pass
            with gr.Row():
                create_extractor_UI(report_state)
                with gr.Column():
                    gr.Markdown(
                        """
                        ## Notes
                        The directory lists are newline-separated lists of directories to include or exclude. The directories must be absolute paths. The included directories will be scanned for files, and the excluded directories will have their files excluded/removed from the database.
                        
                        The 'Update Directory Lists and Scan New Entries' button will update the directory lists, scan newly included directories, and generate tags for files that don't have them.
                        
                        The 'Rescan all Directories' button will rescan all directories. But it will not update the directory lists or generate tags.

                        The 'Generate Tags for Files Missing Tags' button will generate tags for all items that don't have tags set by the selected model(s).

                        The 'Delete ALL Tags set by selected Model(s)' button will delete all tags set by the selected model(s) for all items from the database.                        
                        """
                    )
            with gr.Row():
                report_textbox = gr.Textbox(
                    label="Scan Report", interactive=False, lines=8, value=""
                )

            with gr.Row():
                with gr.Tabs():
                    with gr.TabItem(label="Scan History"):
                        scan_history = create_scan_dataset()
                    with gr.TabItem(label="Tagging History"):
                        tagging_history = create_job_dataset()

        scan_tab.select(
            fn=fetch_all_history,
            outputs=[scan_history, tagging_history],
            api_name="fetch_history",
        )

        update_button.click(
            fn=update_folders,
            inputs=[
                included_directory_list,
                excluded_directory_list,
                delete_unavailable_files,
            ],
            outputs=[
                report_textbox,
                included_directory_list,
                excluded_directory_list,
                scan_history,
                tagging_history,
            ],
            api_name="update_folder_lists",
        )

        scan_button.click(
            fn=rescan_folders,
            inputs=[delete_unavailable_files],
            outputs=[report_textbox, scan_history, tagging_history],
            api_name="rescan_folders",
        )

        report_state.change(
            fn=report_state_change,
            inputs=[report_state],
            outputs=[report_textbox, scan_history, tagging_history],
        )

        # regenerate_tags_button.click(
        #     fn=regenerate_tags,
        #     inputs=[model_choice],
        #     outputs=[results, scan_history, tagging_history],
        #     api_name="regenerate_tags",
        # )

        # delete_tags_button.click(
        #     fn=delete_tags,
        #     inputs=[model_choice],
        #     outputs=[results, scan_history, tagging_history],
        #     api_name="delete_tags",
        # )

        # generate_embeds_button.click(
        #     fn=generate_embeds,
        #     outputs=[results, scan_history, tagging_history],
        #     api_name="generate_embeds",
        # )

        # extract_text_ocr.click(
        #     fn=run_ocr,
        #     outputs=[results, scan_history, tagging_history],
        #     api_name="run_ocr",
        # )

        # extract_whisper.click(
        #     fn=run_whisper,
        #     outputs=[results, scan_history, tagging_history],
        #     api_name="run_whisper",
        # )
