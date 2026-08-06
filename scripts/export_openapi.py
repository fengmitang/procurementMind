"""Export the backend OpenAPI contract as deterministic JSON."""

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

DEFAULT_OUTPUT = Path("docs/baseline/openapi-backend-v0.1.json")


def main() -> None:
    from app.main import app

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        app.openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    arguments.output.write_text(f"{content}\n", encoding="utf-8")
    print(f"OpenAPI contract exported to {arguments.output}.")


if __name__ == "__main__":
    main()
