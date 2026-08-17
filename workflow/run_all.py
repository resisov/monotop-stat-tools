#!/usr/bin/env python3
"""Run the complete five-stage monotop workflow for one configured era."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from common import DEFAULT_CONFIG, DEFAULT_OUTPUT


WORKFLOW_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--combine-prefix", type=Path)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    args = parse_args()
    python = sys.executable
    build = [
        python,
        str(WORKFLOW_DIR / "build_model.py"),
        "--config",
        str(args.config),
        "--output",
        str(args.output),
    ]
    if args.input:
        build.extend(["--input", str(args.input)])
    run(build)
    run([python, str(WORKFLOW_DIR / "plot_transfer_factors.py"), "--output", str(args.output)])
    run([python, str(WORKFLOW_DIR / "plot_region_yields.py"), "--output", str(args.output)])

    limits = [
        python,
        str(WORKFLOW_DIR / "run_limits.py"),
        "--output",
        str(args.output),
        "--workers",
        str(args.workers),
    ]
    impacts = [
        python,
        str(WORKFLOW_DIR / "run_impacts.py"),
        "--output",
        str(args.output),
        "--workers",
        str(args.workers),
    ]
    if args.combine_prefix:
        limits.extend(["--combine-prefix", str(args.combine_prefix)])
        impacts.extend(["--combine-prefix", str(args.combine_prefix)])
    if args.force:
        limits.append("--force")
        impacts.append("--force")
    run(limits)
    run([python, str(WORKFLOW_DIR / "interpolate_limits.py"), "--output", str(args.output)])
    run(
        [
            python,
            str(WORKFLOW_DIR / "interpolate_limits.py"),
            "--output",
            str(args.output),
            "--shell-mode",
            "on-shell-only",
            "--subdirectory",
            "interpolation_on_shell_only",
        ]
    )
    run(
        [
            python,
            str(WORKFLOW_DIR / "plot_brazil_limit.py"),
            "--output",
            str(args.output),
            "--mx",
            "200",
            "--xmin",
            "500",
            "--xmax",
            "2000",
            "--shell-mode",
            "on-shell-only",
            "--subdirectory",
            "interpolation_on_shell_only",
        ]
    )
    run(impacts)
    run([python, str(WORKFLOW_DIR / "validate_outputs.py"), "--output", str(args.output)])


if __name__ == "__main__":
    main()
