"""Deterministic evaluation contracts shared by fake and real model runs."""

from agent_app.evaluation.aggregate import build_unified_report, compare_with_baseline
from agent_app.evaluation.delivery import DeliveryDemoReport, DeliveryDemoRunner
from agent_app.evaluation.runner import EvaluationRunner
from agent_app.evaluation.schemas import (
    EvaluationBaseline,
    EvaluationCase,
    EvaluationReport,
    UnifiedEvaluationReport,
)

__all__ = [
    "EvaluationBaseline",
    "EvaluationCase",
    "EvaluationReport",
    "EvaluationRunner",
    "DeliveryDemoReport",
    "DeliveryDemoRunner",
    "UnifiedEvaluationReport",
    "build_unified_report",
    "compare_with_baseline",
]
