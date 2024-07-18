import sqlite3
from typing import List

from chromadb.api import ClientAPI

from src.data_extractors.wd_tagger import V3_MODELS


class ModelOpts:
    def __str__(self):
        return self.setter_id()

    def __repr__(self):
        return self.setter_id()

    def model_type(self) -> str:
        raise NotImplementedError

    def model_name(self) -> str:
        raise NotImplementedError

    def batch_size(self) -> int:
        raise NotImplementedError

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        raise NotImplementedError

    def setter_id(self) -> str:
        return f"{self.model_type()}|{self.model_name()}"


class TaggerModel(ModelOpts):
    _model_repo: str
    _batch_size: int

    def __init__(self, batch_size: int = 64, model_repo: str = V3_MODELS[0]):
        assert (
            model_repo in TaggerModel.available_models()
        ), f"Invalid model repo {model_repo}"
        self._model_repo = model_repo
        self._batch_size = batch_size

    @classmethod
    def available_models(cls) -> List[str]:
        return V3_MODELS

    def model_type(self) -> str:
        return "tagger"

    def model_name(self) -> str:
        return self._model_repo

    def setter_id(self) -> str:
        return super().setter_id()

    def batch_size(self) -> int:
        return self._batch_size

    def model_repo(self) -> str:
        return self._model_repo

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.tags import run_tag_extractor_job

        return run_tag_extractor_job(conn, self)


class OCRModel(ModelOpts):
    _detection_model: str
    _recognition_model: str
    _batch_size: int

    def __init__(
        self,
        batch_size: int = 64,
        detection_model="db_resnet50",
        recognition_model="crnn_mobilenet_v3_small",
    ):
        self._detection_model = detection_model
        self._recognition_model = recognition_model
        self._batch_size = batch_size

    def model_type(self) -> str:
        return "ocr"

    def model_name(self) -> str:
        return f"{self._detection_model}|{self._recognition_model}"

    def setter_id(self) -> str:
        return super().setter_id()

    def batch_size(self) -> int:
        return self._batch_size

    def recognition_model(self) -> str:
        return self._recognition_model

    def detection_model(self) -> str:
        return self._detection_model

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.ocr import run_ocr_extractor_job

        return run_ocr_extractor_job(conn, cdb, self)


class ImageEmbeddingModel(ModelOpts):
    _model_name: str
    _checkpoint: str
    _batch_size: int

    def __init__(
        self,
        batch_size: int = 64,
        model_name="ViT-H-14-378-quickgelu",
        pretrained="dfn5b",
    ):

        self._model_name = model_name
        self._checkpoint = pretrained
        self._batch_size = batch_size

    def model_type(self) -> str:
        return "clip"

    def model_name(self) -> str:
        return f"{self._model_name}"

    def model_checkpoint(self) -> str:
        return f"{self._checkpoint}"

    def setter_id(self) -> str:
        return (
            f"{self.model_type()}|{self.model_name()}|{self.model_checkpoint()}"
        )

    def batch_size(self) -> int:
        return self._batch_size

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.image_embeddings import (
            run_image_embedding_extractor_job,
        )

        return run_image_embedding_extractor_job(conn, cdb, self)


class WhisperSTTModel(ModelOpts):
    _model_name: str
    _batch_size: int

    def __init__(self, batch_size: int = 8, model_name="base"):
        self._model_name = model_name
        self._batch_size = batch_size

    def model_type(self) -> str:
        return "stt"

    def model_name(self) -> str:
        return self._model_name

    def setter_id(self) -> str:
        return f"{self.model_type()}|{self.model_name()}"

    def batch_size(self) -> int:
        return self._batch_size

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.whisper import run_whisper_extractor_job

        return run_whisper_extractor_job(conn, cdb, self)
