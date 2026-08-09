from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

RAGDevice = Literal["auto", "cpu", "cuda"]
ResolvedRAGDevice = Literal["cpu", "cuda"]


class LocalRAGModelError(RuntimeError):
    pass


def resolve_rag_device(configured: RAGDevice) -> ResolvedRAGDevice:
    import torch

    if configured == "cpu":
        return "cpu"
    if configured == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if not torch.cuda.is_available():
        raise LocalRAGModelError(
            "RAG_MODEL_DEVICE=cuda，但当前 PyTorch 未检测到可用 CUDA；"
            "请改为 cpu/auto，或安装与运行环境匹配的 CUDA 版 PyTorch"
        )
    return "cuda"


@contextmanager
def offline_model_loading() -> Iterator[None]:
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update({key: "1" for key in keys})
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def require_local_model(path: Path, label: str) -> None:
    if not path.is_absolute() or not path.is_dir():
        raise LocalRAGModelError(f"{label} 模型本地目录不存在：{path}")
    if not (path / "config.json").is_file():
        raise LocalRAGModelError(f"{label} 模型目录不完整，缺少 config.json：{path}")
