import argparse
import json
from pathlib import Path
from typing import Iterable, Optional

from .render import build_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a reproducible Operations KPI Rollup preview")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build HTML, charts, preview EML, and normalized snapshot")
    build.add_argument("--input", required=True, type=Path, help="versioned JSON input snapshot")
    build.add_argument("--output", required=True, type=Path, help="output directory")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "build":
        snapshot = json.loads(args.input.read_text(encoding="utf-8"))
        outputs = build_report(snapshot, args.output)
        for name, path in outputs.items():
            print(f"{name}: {path}")
        return 0
    return 2
