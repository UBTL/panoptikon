import sqlite3
from typing import Any, Dict, List, Tuple

from chromadb.api import ClientAPI


class ModelOpts:
    _batch_size: int

    def __init__(
        self, batch_size: int | None = 64, model_name: str | None = None
    ):
        self._batch_size = batch_size or self.default_batch_size()
        if model_name is None:
            model_name = self.default_model()
        assert self.valid_model(model_name), f"Invalid model {model_name}"

        self._init(model_name)

    def __str__(self):
        return self.setter_id()

    def __repr__(self):
        return self.setter_id()

    def batch_size(self) -> int:
        return self._batch_size

    @classmethod
    def available_models(cls) -> List[str]:
        return list(cls._available_models_mapping().keys())

    @classmethod
    def default_batch_size(cls) -> int:
        return 64

    @classmethod
    def valid_model(cls, model_name: str) -> bool:
        return model_name in cls.available_models()

    @classmethod
    def default_model(cls) -> str:
        return cls.available_models()[0]

    def model_type(self) -> str:
        raise NotImplementedError

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        raise NotImplementedError

    def setter_id(self) -> str:
        raise NotImplementedError

    @classmethod
    def _available_models_mapping(cls) -> Dict[str, Any]:
        raise NotImplementedError

    def _init(self, model_name: str):
        raise NotImplementedError


class TagsModel(ModelOpts):
    _model_repo: str

    def _init(self, model_name: str):
        self._model_repo = TagsModel._available_models_mapping()[model_name]

    def model_type(self) -> str:
        return "tags"

    def setter_id(self) -> str:
        return TagsModel._model_to_setter_id(self.model_repo())

    @classmethod
    def default_model(cls) -> str:
        return "wd-swinv2-tagger-v3"

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.extractor_jobs.tags import (
            run_tag_extractor_job,
        )

        return run_tag_extractor_job(conn, self)

    @classmethod
    def _available_models_mapping(cls) -> Dict[str, str]:
        # Dataset v3 series of models:
        SWINV2_MODEL_DSV3_REPO = "SmilingWolf/wd-swinv2-tagger-v3"
        CONV_MODEL_DSV3_REPO = "SmilingWolf/wd-convnext-tagger-v3"
        VIT_MODEL_DSV3_REPO = "SmilingWolf/wd-vit-tagger-v3"

        V3_MODELS = [
            SWINV2_MODEL_DSV3_REPO,
            CONV_MODEL_DSV3_REPO,
            VIT_MODEL_DSV3_REPO,
        ]

        # Dataset v2 series of models:
        MOAT_MODEL_DSV2_REPO = "SmilingWolf/wd-v1-4-moat-tagger-v2"
        SWIN_MODEL_DSV2_REPO = "SmilingWolf/wd-v1-4-swinv2-tagger-v2"
        CONV_MODEL_DSV2_REPO = "SmilingWolf/wd-v1-4-convnext-tagger-v2"
        CONV2_MODEL_DSV2_REPO = "SmilingWolf/wd-v1-4-convnextv2-tagger-v2"
        VIT_MODEL_DSV2_REPO = "SmilingWolf/wd-v1-4-vit-tagger-v2"
        return {name.split("/")[-1]: name for name in V3_MODELS}

    @classmethod
    def _model_to_setter_id(cls, model_repo: str) -> str:
        # Reverse the available models dict
        model_to_name = {
            v: k for k, v in cls._available_models_mapping().items()
        }
        return model_to_name[model_repo]

    # Own methods
    def model_repo(self) -> str:
        return self._model_repo


class OCRModel(ModelOpts):
    _detection_model: str
    _recognition_model: str

    def _init(self, model_name: str):
        self._detection_model, self._recognition_model = (
            OCRModel._available_models_mapping()[model_name]
        )

    def model_type(self) -> str:
        return "ocr"

    def setter_id(self) -> str:
        return OCRModel._model_to_setter_id(
            self.detection_model(), self.recognition_model()
        )

    @classmethod
    def default_model(cls) -> str:
        return "db_resnet50|crnn_mobilenet_v3_small"

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.extractor_jobs.ocr import run_ocr_extractor_job

        return run_ocr_extractor_job(conn, cdb, self)

    @classmethod
    def _available_models_mapping(cls) -> Dict[str, Tuple[str, str]]:
        options = [
            ("db_resnet50", "crnn_vgg16_bn"),
            ("db_resnet50", "crnn_mobilenet_v3_small"),
            ("db_resnet50", "crnn_mobilenet_v3_large"),
            ("db_resnet50", "master"),
            ("db_resnet50", "vitstr_small"),
            ("db_resnet50", "vitstr_base"),
            ("db_resnet50", "parseq"),
        ]
        return {
            f"{detection}|{recognition}": (detection, recognition)
            for detection, recognition in options
        }

    @classmethod
    def _model_to_setter_id(
        cls, detection_model: str, recognition_model: str
    ) -> str:
        # Reverse the available models dict
        model_to_name = {
            v: k for k, v in cls._available_models_mapping().items()
        }
        return model_to_name[(detection_model, recognition_model)]

    def recognition_model(self) -> str:
        return self._recognition_model

    def detection_model(self) -> str:
        return self._detection_model


class ImageEmbeddingModel(ModelOpts):
    _model_name: str
    _checkpoint: str

    def _init(self, model_name: str):

        self._model_name, self._checkpoint = (
            ImageEmbeddingModel._available_models_mapping()[model_name]
        )

    def model_type(self) -> str:
        return "clip"

    def setter_id(self) -> str:
        return ImageEmbeddingModel._model_to_setter_id(
            self.clip_model_name(), self.clip_model_checkpoint()
        )

    @classmethod
    def default_model(cls) -> str:
        return "ViT-H-14-378-quickgelu|dfn5b"

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.extractor_jobs.clip import (
            run_image_embedding_extractor_job,
        )

        return run_image_embedding_extractor_job(conn, cdb, self)

    @classmethod
    def _available_models_mapping(cls) -> Dict[str, Tuple[str, str]]:
        from src.data_extractors.ai.clip_model_list import CLIP_CHECKPOINTS

        return {
            f"{model_name}|{checkpoint}": (model_name, checkpoint)
            for model_name, checkpoint in CLIP_CHECKPOINTS
        }

    @classmethod
    def _model_to_setter_id(cls, model_name: str, checkpoint: str) -> str:
        # Reverse the available models dict
        model_to_name = {
            v: k for k, v in cls._available_models_mapping().items()
        }
        return model_to_name[(model_name, checkpoint)]

    def clip_model_name(self) -> str:
        return self._model_name

    def clip_model_checkpoint(self) -> str:
        return self._checkpoint


class WhisperSTTModel(ModelOpts):
    _model_repo: str

    def _init(self, model_name: str):
        self._model_repo = WhisperSTTModel._available_models_mapping()[
            model_name
        ]

    @classmethod
    def default_batch_size(cls) -> int:
        return 8

    @classmethod
    def default_model(cls) -> str:
        return "distill-large-v3"

    def model_type(self) -> str:
        return "stt"

    def setter_id(self) -> str:
        return WhisperSTTModel._model_to_setter_id(self.model_repo())

    def run_extractor(self, conn: sqlite3.Connection, cdb: ClientAPI):
        from src.data_extractors.extractor_jobs.whisper import (
            run_whisper_extractor_job,
        )

        return run_whisper_extractor_job(conn, cdb, self)

    @classmethod
    def _available_models_mapping(cls) -> Dict[str, str]:
        _MODELS = {
            "tiny.en": "Systran/faster-whisper-tiny.en",
            "tiny": "Systran/faster-whisper-tiny",
            "base.en": "Systran/faster-whisper-base.en",
            "base": "Systran/faster-whisper-base",
            "small.en": "Systran/faster-whisper-small.en",
            "small": "Systran/faster-whisper-small",
            "medium.en": "Systran/faster-whisper-medium.en",
            "medium": "Systran/faster-whisper-medium",
            "large-v1": "Systran/faster-whisper-large-v1",
            "large-v2": "Systran/faster-whisper-large-v2",
            "large-v3": "Systran/faster-whisper-large-v3",
            "large": "Systran/faster-whisper-large-v3",
            "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
            "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
            "distil-small.en": "Systran/faster-distil-whisper-small.en",
            "distill-large-v3": "Systran/faster-distil-whisper-large-v3",
        }
        return _MODELS

    @classmethod
    def _model_to_setter_id(cls, model_repo: str) -> str:
        # Reverse the available models dict
        model_to_name = {
            v: k for k, v in cls._available_models_mapping().items()
        }
        return model_to_name[model_repo]

    def model_repo(self) -> str:
        return self._model_repo
