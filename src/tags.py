from __future__ import annotations

import os
from datetime import datetime
import sqlite3

import deepdanbooru as dd
import huggingface_hub
import numpy as np
import PIL.Image
import tensorflow as tf

from src.db import insert_tag, find_working_paths_without_tags

def get_threshold_from_env() -> float:
    threshold = os.getenv("SCORE_THRESHOLD")
    if threshold is None:
        return 0.25
    return float(threshold)

def load_model() -> tf.keras.Model:
    path = huggingface_hub.hf_hub_download("public-data/DeepDanbooru", "model-resnet_custom_v3.h5")
    model = tf.keras.models.load_model(path)
    return model


def load_labels() -> list[str]:
    path = huggingface_hub.hf_hub_download("public-data/DeepDanbooru", "tags.txt")
    with open(path) as f:
        labels = [line.strip() for line in f.readlines()]
    return labels

def predict(image: PIL.Image.Image, score_threshold: float, model: tf.keras.Model, labels: list[str]) -> tuple[dict[str, float], dict[str, float], str]:
    _, height, width, _ = model.input_shape
    image = np.asarray(image)
    image = tf.image.resize(image, size=(height, width), method=tf.image.ResizeMethod.AREA, preserve_aspect_ratio=True)
    image = image.numpy()
    image = dd.image.transform_and_pad_image(image, width, height)
    image = image / 255.0
    probs = model.predict(image[None, ...])[0]
    probs = probs.astype(float)

    indices = np.argsort(probs)[::-1]
    result_all = dict()
    result_threshold = dict()
    for index in indices:
        label = labels[index]
        prob = probs[index]
        result_all[label] = prob
        if prob < score_threshold:
            break
        result_threshold[label] = prob
    result_text = ", ".join(result_all.keys())
    return result_threshold, result_all, result_text

def scan_and_predict_tags(conn: sqlite3.Connection, setter="deepdanbooru"):
    model, labels = None, None
    threshold = get_threshold_from_env()

    scan_time = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO tag_scans (start_time, setter)
    VALUES (?, ?)
    ''', (scan_time, setter))

    for sha256, path in find_working_paths_without_tags(conn, setter).items():
        image = PIL.Image.open(path)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        try:
            if model is None:
                model = load_model()
                labels = load_labels()
            result_threshold, _result_all, _result_text = predict(image, threshold, model, labels)
        except Exception as e:
            print(f"Error processing {path}")
            continue
        for tag, confidence in result_threshold.items():
            insert_tag(
                conn,
                scan_time=scan_time,
                namespace="danbooru",
                name=tag,
                item=sha256,
                confidence=confidence,
                setter=setter,
                value=None
            )
    
    scan_end_time = datetime.now().isoformat()

    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tag_scans
        SET end_time = ?
        WHERE start_time = ? AND setter = ?
    ''', (scan_end_time, scan_time, setter))