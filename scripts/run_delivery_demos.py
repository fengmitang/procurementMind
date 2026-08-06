"""Run repeatable model-independent delivery demos against local Compose services."""

import argparse
import asyncio
import sys
from pathlib import Path

from httpx import AsyncClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=130.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def main() -> int:
    from agent_app.evaluation.delivery import DeliveryDemoRunner

    args = parse_args()
    async with AsyncClient(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        report = await DeliveryDemoRunner(client).run()
    rendered = report.model_dump_json(indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
