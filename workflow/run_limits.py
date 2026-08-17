#!/usr/bin/env python3
"""Run local CMS Combine asymptotic limits for every signal mass point."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import uproot

from common import (
    DEFAULT_OUTPUT,
    combine_environment,
    ensure_directories,
    run_command,
    write_json,
)


QUANTILES = {
    0.025: "expected_minus2",
    0.16: "expected_minus1",
    0.5: "expected",
    0.84: "expected_plus1",
    0.975: "expected_plus2",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--combine-prefix",
        type=Path,
        default=Path(os.environ["COMBINE_PREFIX"])
        if "COMBINE_PREFIX" in os.environ
        else None,
        help="Standalone Combine install prefix; omit when Combine is already on PATH",
    )
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument(
        "--signal",
        action="append",
        help="Run only this source signal name or mphi*_mchi* label; repeatable",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def read_limit_file(path: Path) -> dict[str, float]:
    with uproot.open(path) as root_file:
        tree = root_file["limit"]
        limits = np.asarray(tree["limit"].array(library="np"), dtype=float)
        quantiles = np.asarray(tree["quantileExpected"].array(library="np"), dtype=float)
    result: dict[str, float] = {}
    for target, name in QUANTILES.items():
        index = int(np.argmin(np.abs(quantiles - target)))
        if abs(float(quantiles[index]) - target) > 0.01:
            raise RuntimeError(f"Missing quantile {target} in {path}")
        result[name] = float(limits[index])
    return result


def run_one(
    signal: dict[str, Any],
    *,
    output: Path,
    env: dict[str, str],
    force: bool,
) -> dict[str, Any]:
    label = str(signal["label"])
    datacard = output / str(signal["datacard"])
    workspace = output / "workspaces" / f"workspace_{label}.root"
    raw_dir = output / "limits" / "raw"
    logs_dir = output / "logs"
    root_name = f"higgsCombine.{label}.AsymptoticLimits.mH125.root"
    root_path = raw_dir / root_name

    if force or not workspace.exists():
        run_command(
            [
                "text2workspace.py",
                datacard.name,
                "-m",
                "125",
                "-o",
                str(workspace),
            ],
            cwd=datacard.parent,
            log_path=logs_dir / f"text2workspace_{label}.log",
            env=env,
        )
        if not workspace.exists():
            raise RuntimeError(f"text2workspace did not create {workspace}")

    rmax = float(signal["recommended_rmax"])
    if not math.isfinite(rmax) or rmax <= 0.0:
        rmax = 1.0e7
    rmax = min(max(rmax, 10.0), 1.0e7)
    parsed: dict[str, float] | None = None
    for attempt in range(3):
        if root_path.exists():
            root_path.unlink()
        command = [
            "combine",
            "-M",
            "AsymptoticLimits",
            str(workspace),
            "-m",
            "125",
            "-n",
            f".{label}",
            "--rMin",
            "0",
            "--rMax",
            f"{rmax:.10g}",
            "--run",
            "blind",
            "--cminDefaultMinimizerStrategy",
            "0" if attempt < 2 else "1",
            "--X-rtd",
            "MINIMIZER_analytic",
            "--X-rtd",
            "FAST_VERTICAL_MORPH",
        ]
        run_command(
            command,
            cwd=raw_dir,
            log_path=logs_dir / f"limit_{label}_attempt{attempt + 1}.log",
            env=env,
        )
        if not root_path.exists():
            raise RuntimeError(f"Combine did not create {root_path}")
        parsed = read_limit_file(root_path)
        if max(parsed.values()) < 0.9 * rmax or rmax >= 1.0e7:
            break
        rmax = min(rmax * 10.0, 1.0e7)

    if parsed is None:
        raise RuntimeError(f"No limit result produced for {label}")
    return {
        "source_name": signal["source_name"],
        "label": label,
        "mphi": int(signal["mphi"]),
        "mchi": int(signal["mchi"]),
        "sr_signal_yield": float(signal["sr_signal_yield"]),
        "rmax": rmax,
        **parsed,
        "root_file": str(root_path.relative_to(output)),
        "status": "ok",
    }


def write_results(output: Path, rows: list[dict[str, Any]]) -> None:
    rows.sort(key=lambda row: (row["mphi"], row["mchi"]))
    limits_dir = output / "limits"
    write_json(limits_dir / "limits.json", rows)
    fields = [
        "source_name",
        "label",
        "mphi",
        "mchi",
        "sr_signal_yield",
        "expected_minus2",
        "expected_minus1",
        "expected",
        "expected_plus1",
        "expected_plus2",
        "rmax",
        "status",
        "root_file",
    ]
    with (limits_dir / "limits.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tree_payload = {
        field: np.asarray([row[field] for row in rows], dtype=np.float64)
        for field in [
            "mphi",
            "mchi",
            "sr_signal_yield",
            "expected_minus2",
            "expected_minus1",
            "expected",
            "expected_plus1",
            "expected_plus2",
        ]
    }
    with uproot.recreate(limits_dir / "limits.root") as root_file:
        root_file["limit"] = tree_payload


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    signals = list(manifest["signals"])
    if args.signal:
        selected = set(args.signal)
        signals = [
            signal
            for signal in signals
            if signal["source_name"] in selected or signal["label"] in selected
        ]
        missing = selected - {
            value
            for signal in signals
            for value in [signal["source_name"], signal["label"]]
        }
        if missing:
            raise SystemExit(f"Unknown signal selection(s): {sorted(missing)}")

    ensure_directories(
        [
            output / "workspaces",
            output / "logs",
            output / "limits",
            output / "limits" / "raw",
        ]
    )
    env = combine_environment(args.combine_prefix)
    rows: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                run_one,
                signal,
                output=output,
                env=env,
                force=args.force,
            ): signal
            for signal in signals
        }
        for future in as_completed(futures):
            signal = futures[future]
            try:
                row = future.result()
                rows.append(row)
                print(
                    f"[{len(rows):02d}/{len(signals):02d}] {row['label']}: "
                    f"expected={row['expected']:.5g} (blinded)",
                    flush=True,
                )
            except Exception as error:  # keep successful points and report all failures
                failures.append((str(signal["label"]), str(error)))
                print(f"FAILED {signal['label']}: {error}", flush=True)

    if rows:
        write_results(output, rows)
    if failures:
        write_json(
            output / "limits" / "failures.json",
            [{"label": label, "error": error} for label, error in failures],
        )
        raise SystemExit(f"{len(failures)} of {len(signals)} limit jobs failed")
    print(f"Wrote {len(rows)} limits to {output / 'limits' / 'limits.csv'}")


if __name__ == "__main__":
    main()
