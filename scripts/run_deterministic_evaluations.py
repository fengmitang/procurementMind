import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASELINE = ROOT / "docs" / "baseline" / "deterministic-evaluation-baseline-v0.2.json"


async def main() -> int:
    from agent_app.evaluation import (
        EvaluationBaseline,
        build_unified_report,
        compare_with_baseline,
    )
    from agent_app.evaluation.deterministic import (
        load_deterministic_cases,
        run_deterministic_suites,
    )

    parser = argparse.ArgumentParser(description="运行采购 Agent 确定性评测并对比只读基线")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    cases = load_deterministic_cases(ROOT / "tests" / "fixtures")
    reports = await run_deterministic_suites(
        router_cases=cases.router,
        tool_cases=cases.tool,
        analysis_cases=cases.analysis,
        risk_cases=cases.risk,
    )
    report = build_unified_report(reports)
    baseline = EvaluationBaseline.model_validate_json(args.baseline.read_text(encoding="utf-8"))
    comparison = compare_with_baseline(report, baseline)
    payload = {
        "report": report.model_dump(mode="json"),
        "baseline_comparison": comparison.model_dump(mode="json"),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if comparison.passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
