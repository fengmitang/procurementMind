"""Verify the two local procurement RAG models with CPU-only inference."""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERY = "采购申请被楼长驳回后应该怎么办？"
CANDIDATES = [
    "申请被驳回后，需求人应根据驳回原因修改申请内容，并重新提交审核。",
    "仓库管理员负责登记设备入库位置和实收数量。",
]


def vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def main() -> int:
    import torch

    from agent_app.core.config import get_agent_settings
    from agent_app.rag.models import initialize_local_rag_models

    settings = get_agent_settings()
    if settings.rag_model_device != "cpu":
        raise RuntimeError("本阶段只允许 RAG_MODEL_DEVICE=cpu")
    models = initialize_local_rag_models(settings)
    if models is None:
        raise RuntimeError("EMBEDDING_MODEL_PATH 和 RERANKER_MODEL_PATH 尚未配置")
    if models.device != "cpu":
        raise RuntimeError(f"模型未运行在 CPU：{models.device}")

    vectors = models.encode_dense([QUERY, CANDIDATES[0]])
    if len(vectors) != 2 or not vectors[0] or len(vectors[0]) != len(vectors[1]):
        raise RuntimeError("BGE-M3 未为两段文本生成维度一致的有效向量")
    norms = [vector_norm(vector) for vector in vectors]
    if not all(math.isfinite(value) for value in norms):
        raise RuntimeError("BGE-M3 生成的向量包含无效数值")

    scores = models.rerank(QUERY, CANDIDATES)
    if len(scores) != 2 or not all(math.isfinite(score) for score in scores):
        raise RuntimeError("Reranker 未生成两个有效相关性分数")
    if scores[0] <= scores[1] or scores[0] - scores[1] < 0.1:
        raise RuntimeError("Reranker 未将明显相关的 Candidate A 排在 Candidate B 之前")

    print("device=cpu")
    print(f"torch_cuda_build={torch.version.cuda}")
    print(f"torch_cuda_available={torch.cuda.is_available()}")
    print(f"embedding_count={len(vectors)}")
    print(f"embedding_dimension={len(vectors[0])}")
    print(f"embedding_norms={[round(value, 6) for value in norms]}")
    print(f"candidate_a_score={scores[0]:.6f}")
    print(f"candidate_b_score={scores[1]:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
