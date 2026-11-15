"""Command-line demonstration for PathContext."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ingest import load_fixture
from pathcontext.context_compiler import ContextCompiler


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile structural incident context")
    parser.add_argument("--question", default="Which change caused INC-1042 and who owns it?")
    parser.add_argument("--budget", type=int, default=800)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "incidents.json",
    )
    args = parser.parse_args()
    result = ContextCompiler(load_fixture(args.fixture)).compile(
        args.question, context_budget_tokens=args.budget
    )
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
