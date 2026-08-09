"""Download procurementMind RAG models to explicit non-project F: directories."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_ROOT = Path("F:/AIModels")
DEFAULT_EMBEDDING_PATH = DEFAULT_MODEL_ROOT / "bge-m3"
DEFAULT_RERANKER_PATH = DEFAULT_MODEL_ROOT / "bge-reranker-v2-m3"

MODELS = (
    ("BAAI/bge-m3", DEFAULT_EMBEDDING_PATH),
    ("BAAI/bge-reranker-v2-m3", DEFAULT_RERANKER_PATH),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--max-workers", type=int, default=4)
    return parser.parse_args()


def ensure_external_directory(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return resolved
    raise ValueError(f"模型目录不能位于项目目录中：{resolved}")


def configure_huggingface_storage(model_root: Path) -> None:
    hub_root = model_root / ".huggingface"
    os.environ["HF_HOME"] = str(hub_root)
    os.environ["HF_HUB_CACHE"] = str(hub_root / "hub")
    os.environ["HF_XET_CACHE"] = str(hub_root / "xet")
    os.environ["HF_ASSETS_CACHE"] = str(hub_root / "assets")


def main() -> int:
    args = parse_args()
    model_root = ensure_external_directory(args.model_root)
    model_root.mkdir(parents=True, exist_ok=True)
    configure_huggingface_storage(model_root)

    from huggingface_hub import snapshot_download

    for repo_id, default_path in MODELS:
        target = model_root / default_path.name
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {repo_id} -> {target}")
        snapshot_download(
            repo_id=repo_id,
            revision=args.revision,
            local_dir=target,
            max_workers=args.max_workers,
            ignore_patterns=["*.onnx", "onnx/**", "openvino/**", "*.h5", "*.msgpack"],
        )
        if not (target / "config.json").is_file():
            raise RuntimeError(f"下载结果不完整，缺少 config.json：{target}")
    print("RAG model downloads completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
