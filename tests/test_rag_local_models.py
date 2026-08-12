from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_app import main as agent_main
from agent_app.core.config import AgentSettings
from agent_app.rag import models as rag_models_module
from agent_app.rag._local import resolve_rag_device
from agent_app.rag.models import (
    LocalRAGModelError,
    LocalRAGModels,
    get_local_rag_models,
    initialize_local_rag_models,
    initialize_rag_providers,
)
from scripts.download_rag_models import ensure_external_directory


def model_directories(tmp_path: Path) -> tuple[Path, Path]:
    embedding = tmp_path / "bge-m3"
    reranker = tmp_path / "bge-reranker-v2-m3"
    embedding.mkdir()
    reranker.mkdir()
    (embedding / "config.json").write_text("{}", encoding="utf-8")
    (reranker / "config.json").write_text("{}", encoding="utf-8")
    return embedding, reranker


def settings(**updates: object) -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret="rag-test-secret-123",
        **updates,
    )


def test_rag_paths_and_device_are_explicit_settings(tmp_path: Path) -> None:
    embedding, reranker = model_directories(tmp_path)
    value = settings(
        embedding_model_path=embedding,
        reranker_model_path=reranker,
        rag_embedding_provider="local_bge",
        rag_rerank_provider="local_bge",
        rag_model_device="cpu",
    )

    assert value.rag_models_configured is True
    assert value.embedding_model_path == embedding
    assert value.reranker_model_path == reranker
    assert value.rag_model_device == "cpu"


def test_partial_local_model_configuration_is_rejected(tmp_path: Path) -> None:
    embedding, _ = model_directories(tmp_path)

    with pytest.raises(LocalRAGModelError, match="必须同时配置"):
        initialize_local_rag_models(settings(embedding_model_path=embedding))


def test_model_service_initializes_only_once_and_runs_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_path, reranker_path = model_directories(tmp_path)
    calls = {"embedding": 0, "reranker": 0}

    class FakeEmbedding:
        def __init__(self, path: str, **kwargs: object) -> None:
            assert Path(path) == embedding_path
            assert kwargs == {"use_fp16": False, "devices": "cpu"}
            calls["embedding"] += 1

        def encode(self, texts: list[str], **_kwargs: object) -> dict:
            return {"dense_vecs": [[1.0, 0.0, 0.5] for _ in texts]}

    class FakeReranker:
        def __init__(self, path: str, **kwargs: object) -> None:
            assert Path(path) == reranker_path
            assert kwargs == {"use_fp16": False, "devices": "cpu"}
            calls["reranker"] += 1

        def compute_score(self, pairs: list[list[str]], **_kwargs: object) -> list[float]:
            return [0.9 if "采购" in document else 0.1 for _, document in pairs]

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        SimpleNamespace(BGEM3FlagModel=FakeEmbedding, FlagReranker=FakeReranker),
    )
    service = LocalRAGModels(embedding_path, reranker_path, "cpu")

    assert service.initialize() is service
    assert service.initialize() is service
    assert service.encode_dense(["采购流程"]) == [[1.0, 0.0, 0.5]]
    assert service.rerank("采购", ["采购制度", "天气预报"]) == [0.9, 0.1]
    assert calls == {"embedding": 1, "reranker": 1}


@pytest.mark.parametrize("device", ["auto", "cpu", "cuda"])
def test_all_supported_device_modes_are_valid_configuration(device: str) -> None:
    assert settings(rag_model_device=device).rag_model_device == device


def test_bailian_rag_configuration_reuses_existing_llm_credentials() -> None:
    value = settings(
        model_api_key="credential-placeholder",
        model_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )

    assert value.rag_models_configured is True
    assert value.resolved_rag_api_key is value.model_api_key
    assert value.resolved_rag_bailian_base_url == value.model_base_url
    assert value.rag_embedding_model == "qwen3.7-text-embedding"
    assert value.rag_rerank_model == "qwen3-rerank"


def test_auto_device_can_resolve_to_cpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_path, reranker_path = model_directories(tmp_path)
    monkeypatch.setattr(rag_models_module, "resolve_rag_device", lambda _device: "cpu")

    service = LocalRAGModels(embedding_path, reranker_path, "auto")

    assert service.configured_device == "auto"
    assert service.device == "cpu"


def test_explicit_cuda_fails_clearly_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    with pytest.raises(LocalRAGModelError, match="未检测到可用 CUDA"):
        resolve_rag_device("cuda")


def test_model_loading_failure_has_clear_local_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_path, reranker_path = model_directories(tmp_path)

    class BrokenEmbedding:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise OSError("权重文件损坏")

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        SimpleNamespace(BGEM3FlagModel=BrokenEmbedding),
    )

    with pytest.raises(LocalRAGModelError, match="Embedding 模型从本地目录加载失败"):
        LocalRAGModels(embedding_path, reranker_path, "cpu").initialize()


def test_process_cache_reuses_same_model_service(tmp_path: Path) -> None:
    embedding, reranker = model_directories(tmp_path)
    get_local_rag_models.cache_clear()

    first = get_local_rag_models(str(embedding), str(reranker), "cpu")
    second = get_local_rag_models(str(embedding), str(reranker), "cpu")

    assert first is second


def test_provider_factory_supports_full_local_bge_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_path, reranker_path = model_directories(tmp_path)

    class FakeEmbedding:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def encode(self, texts: list[str], **_kwargs: object) -> dict:
            return {"dense_vecs": [[1.0, 0.0] for _ in texts]}

    class FakeReranker:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def compute_score(self, pairs: list[list[str]], **_kwargs: object) -> list[float]:
            return [0.9 for _ in pairs]

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        SimpleNamespace(BGEM3FlagModel=FakeEmbedding, FlagReranker=FakeReranker),
    )
    providers = initialize_rag_providers(
        settings(
            embedding_model_path=embedding_path,
            reranker_model_path=reranker_path,
            rag_embedding_provider="local_bge",
            rag_rerank_provider="local_bge",
            rag_model_device="cpu",
        )
    )

    assert providers is not None
    assert providers.encode_dense(["采购规则"]) == [[1.0, 0.0]]
    assert providers.rerank("采购", ["采购规则"]) == [0.9]


@pytest.mark.asyncio
async def test_service_lifespan_initializes_local_models_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding, reranker = model_directories(tmp_path)
    configured_settings = settings(
        embedding_model_path=embedding,
        reranker_model_path=reranker,
        rag_embedding_provider="local_bge",
        rag_rerank_provider="local_bge",
        rag_model_device="cpu",
    )
    sentinel = SimpleNamespace(name="local-rag-models")
    calls = 0

    def fake_initialize(value: AgentSettings) -> object:
        nonlocal calls
        assert value is configured_settings
        calls += 1
        return sentinel

    monkeypatch.setattr(agent_main, "initialize_rag_providers", fake_initialize)
    application = agent_main.create_agent_app(
        configured_settings,
        procurement_backend_client=SimpleNamespace(),
        graph_service=SimpleNamespace(),
    )

    async with application.router.lifespan_context(application):
        assert application.state.rag_models is sentinel
        assert calls == 1

    assert calls == 1


def test_download_script_rejects_project_directory() -> None:
    with pytest.raises(ValueError, match="不能位于项目目录"):
        ensure_external_directory(Path("models"))


def test_environment_example_declares_local_rag_model_contract() -> None:
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "EMBEDDING_MODEL_PATH=F:/AIModels/bge-m3" in content
    assert "RERANKER_MODEL_PATH=F:/AIModels/bge-reranker-v2-m3" in content
    assert "RAG_MODEL_DEVICE=cpu" in content
    assert "\nEMBEDDING_MODEL=" not in content
    assert "RAG_EMBEDDING_PROVIDER=aliyun_bailian" in content
    assert "RAG_RERANK_PROVIDER=aliyun_bailian" in content
