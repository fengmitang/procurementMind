from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from agent_app.rag._local import (
    LocalRAGModelError,
    ResolvedRAGDevice,
    offline_model_loading,
    require_local_model,
)


class BGERerankerModel:
    """BGE reranker adapter with an explicitly resolved device."""

    def __init__(self, model_path: Path, device: ResolvedRAGDevice) -> None:
        self.model_path = model_path.resolve()
        self.device = device
        self._model: Any | None = None
        self._initialization_lock = Lock()

    @property
    def initialized(self) -> bool:
        return self._model is not None

    def initialize(self) -> BGERerankerModel:
        if self.initialized:
            return self
        with self._initialization_lock:
            if self.initialized:
                return self
            require_local_model(self.model_path, "Reranker")
            try:
                with offline_model_loading():
                    from FlagEmbedding import FlagReranker

                    self._model = FlagReranker(
                        str(self.model_path),
                        use_fp16=self.device == "cuda",
                        devices=self.device,
                    )
            except Exception as exc:
                raise LocalRAGModelError(
                    f"Reranker 模型从本地目录加载失败：{self.model_path}；{exc}"
                ) from exc
        return self

    def score(
        self,
        query: str,
        documents: list[str],
        *,
        normalize: bool = True,
        batch_size: int = 4,
    ) -> list[float]:
        if not query.strip() or not documents or any(not item.strip() for item in documents):
            raise ValueError("Reranker query 和 documents 不能为空")
        model = self.initialize()._model
        result = model.compute_score(
            [[query, document] for document in documents],
            normalize=normalize,
            batch_size=batch_size,
        )
        if isinstance(result, (float, int)):
            return [float(result)]
        return [float(score) for score in result]
