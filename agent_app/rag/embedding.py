from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock
from typing import Any

from agent_app.rag._local import (
    LocalRAGModelError,
    ResolvedRAGDevice,
    offline_model_loading,
    require_local_model,
)


class BGEEmbeddingModel:
    """BGE-M3 embedding adapter with an explicitly resolved device."""

    def __init__(self, model_path: Path, device: ResolvedRAGDevice) -> None:
        self.model_path = model_path.resolve()
        self.device = device
        self._model: Any | None = None
        self._initialization_lock = Lock()

    @property
    def initialized(self) -> bool:
        return self._model is not None

    @property
    def embedding_cache_identity(self) -> str:
        config = self.model_path / "config.json"
        digest = hashlib.sha256(config.read_bytes()).hexdigest()[:16]
        return f"{self.model_path}|{digest}|bge-m3-dense-v1"

    def initialize(self) -> BGEEmbeddingModel:
        if self.initialized:
            return self
        with self._initialization_lock:
            if self.initialized:
                return self
            require_local_model(self.model_path, "Embedding")
            try:
                with offline_model_loading():
                    from FlagEmbedding import BGEM3FlagModel

                    self._model = BGEM3FlagModel(
                        str(self.model_path),
                        use_fp16=self.device == "cuda",
                        devices=self.device,
                    )
            except Exception as exc:
                raise LocalRAGModelError(
                    f"Embedding 模型从本地目录加载失败：{self.model_path}；{exc}"
                ) from exc
        return self

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int = 4,
        max_length: int = 512,
    ) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding 文本不能为空")
        model = self.initialize()._model
        output = model.encode(
            texts,
            batch_size=batch_size,
            max_length=max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return [[float(value) for value in vector] for vector in output["dense_vecs"]]

    def encode_dense(
        self,
        texts: list[str],
        *,
        batch_size: int = 4,
        max_length: int = 512,
    ) -> list[list[float]]:
        return self.encode(
            texts,
            batch_size=batch_size,
            max_length=max_length,
        )
