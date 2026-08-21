from typing import Any

import pytest

from agent_app.core.config import AgentSettings
from agent_app.graph.service import ProcurementGraphService
from agent_app.models.role_schemas import ReviewOutput
from agent_app.models.runner import StructuredModelRunError


def settings() -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret="review-policy-test-secret",
        procurement_backend_url="http://backend.test",
    )


def state(*, pending_action: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "route": "RISK_INVESTIGATION",
        "message": "调查价格风险",
        "evidence_sufficient": True,
        "pending_action": pending_action,
        "compose_output": {
            "answer": "系统已识别价格风险，建议人工复核。",
            "citations": [],
            "limitations": [],
            "requires_human_confirmation": pending_action is not None,
        },
        "evidence": [
            {
                "evidence_type": "ANALYSIS_RESULT",
                "source": "test",
                "reference_id": "risk-signals",
                "data": {
                    "signals": [
                        {"risk_code": "PRICE", "matched": True, "risk_level": "MEDIUM"}
                    ]
                },
            }
        ],
        "step_count": 1,
        "trace_events": [],
        "errors": [],
    }


class ReviewRoles:
    def __init__(self, output: ReviewOutput | None = None) -> None:
        self.output = output

    async def review(self, *_args: object) -> ReviewOutput:
        if self.output is None:
            raise StructuredModelRunError(
                "MODEL_AUTH_FAILED",
                "Review provider unavailable",
                attempts=1,
                retryable=False,
            )
        return self.output

    @staticmethod
    def trace_metadata(*_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_graph_keeps_original_reply_when_policy_downgrades_model_block_to_warn() -> None:
    model_review = ReviewOutput.model_validate(
        {
            "passed": False,
            "issues": [
                {
                    "code": "ANALYSIS_AS_FACT",
                    "severity": "BLOCKING",
                    "message": "风险措辞偏强",
                    "evidence_ids": ["risk-signals"],
                }
            ],
            "requires_human_confirmation": False,
            "revised_answer": "模型建议替换的回答",
        }
    )
    service = ProcurementGraphService(settings())
    service.model_roles = ReviewRoles(model_review)  # type: ignore[assignment]

    updates = await service._review_node(state())

    assert updates["review_policy"]["decision"] == "WARN"
    assert "reply" not in updates
    assert updates["trace_events"][-1]["status"] == "WARN"


@pytest.mark.asyncio
async def test_graph_review_unavailable_fails_soft_for_read_and_safe_for_write() -> None:
    service = ProcurementGraphService(settings())
    service.model_roles = ReviewRoles()  # type: ignore[assignment]

    read = await service._review_node(state())
    write = await service._review_node(
        state(
            pending_action={
                "action_type": "CREATE_PURCHASE_DRAFT",
                "draft": {"device_name": "测试设备"},
                "requires_confirmation": True,
            }
        )
    )

    assert read["review_policy"]["decision"] == "REVIEW_UNAVAILABLE"
    assert "errors" not in read
    assert write["review_policy"]["decision"] == "REVIEW_UNAVAILABLE"
    assert write["errors"][-1]["code"] == "REVIEW_UNAVAILABLE"
