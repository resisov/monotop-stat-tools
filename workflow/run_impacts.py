#!/usr/bin/env python3
"""Run and plot local CMS Combine impacts for a benchmark signal point."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/codex-monotop-mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter

from common import (
    DEFAULT_OUTPUT,
    combine_environment,
    ensure_directories,
    run_command,
    write_json,
)
from plotting import cms_label, save_png_pdf, use_cms_style


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--combine-prefix",
        type=Path,
        default=Path(os.environ["COMBINE_PREFIX"])
        if "COMBINE_PREFIX" in os.environ
        else None,
    )
    parser.add_argument(
        "--signal",
        help="Source signal name or mphi*_mchi* label; defaults to manifest benchmark",
    )
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--rmin", type=float, default=-5.0)
    parser.add_argument("--rmax", type=float, default=5.0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def sorted_impacts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        payload["params"],
        key=lambda item: abs(float(item.get("impact_r", 0.0))),
        reverse=True,
    )


def impact_figure(
    parameters: list[dict[str, Any]],
    luminosity_fb: float,
) -> plt.Figure:
    names = [str(parameter["name"]) for parameter in parameters]
    down = np.asarray(
        [float(parameter["r"][0]) - float(parameter["r"][1]) for parameter in parameters]
    )
    up = np.asarray(
        [float(parameter["r"][2]) - float(parameter["r"][1]) for parameter in parameters]
    )
    y = np.arange(len(parameters))
    fig, axis = plt.subplots(figsize=(11.0, 11.0))
    axis.barh(
        y,
        down,
        color="#2166ac",
        alpha=0.78,
        height=0.76,
        label=r"Nuisance $-1\sigma$",
    )
    axis.barh(
        y,
        up,
        color="#b2182b",
        alpha=0.78,
        height=0.76,
        label=r"Nuisance $+1\sigma$",
    )
    axis.axvline(0.0, color="black", linewidth=1.0)
    axis.set_yticks(y, labels=names, fontsize=8.5)
    axis.invert_yaxis()
    axis.set_xlabel(r"$\Delta r$")
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _position: f"{value:.2g}"))
    axis.xaxis.get_offset_text().set_visible(False)
    axis.legend(loc="lower right", fontsize=10)
    axis.grid(axis="x", alpha=0.2)
    cms_label(axis, luminosity_fb)
    fig.tight_layout()
    return fig


def impact_summary(parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": parameter["name"],
            "impact_r": float(parameter.get("impact_r", 0.0)),
            "fit": [float(value) for value in parameter["fit"]],
            "delta_r_at_minus1sigma": float(parameter["r"][0])
            - float(parameter["r"][1]),
            "delta_r_at_plus1sigma": float(parameter["r"][2])
            - float(parameter["r"][1]),
            "type": parameter.get("type"),
        }
        for parameter in parameters
    ]


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    luminosity_fb = float(manifest["luminosity_fb"])
    selection = args.signal or manifest["benchmark_signal"]
    matching = [
        signal
        for signal in manifest["signals"]
        if selection in {signal["source_name"], signal["label"]}
    ]
    if len(matching) != 1:
        raise SystemExit(f"Could not resolve exactly one signal from {selection!r}")
    signal = matching[0]
    label = str(signal["label"])
    datacard = output / str(signal["datacard"])
    workspace = output / "workspaces" / f"workspace_{label}.root"
    impacts_dir = output / "impacts"
    raw_dir = impacts_dir / "raw"
    logs_dir = output / "logs"
    ensure_directories([output / "workspaces", impacts_dir, raw_dir, logs_dir])
    env = combine_environment(args.combine_prefix)
    env["MPLCONFIGDIR"] = "/tmp/codex-monotop-mpl"

    if args.force or not workspace.exists():
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
        raise RuntimeError(f"Missing workspace {workspace}")
    # combineTool internally constructs shell command strings, so use a
    # space-free path relative to the raw-fit directory on this workspace.
    workspace_argument = os.path.relpath(workspace, raw_dir)

    common = [
        "-d",
        workspace_argument,
        "-m",
        "125",
        "--robustFit",
        "1",
        "--rMin",
        f"{args.rmin:g}",
        "--rMax",
        f"{args.rmax:g}",
        "--cminDefaultMinimizerStrategy",
        "0",
        "-t",
        "-1",
        "--expectSignal",
        "0",
    ]
    initial_files = list(raw_dir.glob("higgsCombine_initialFit_Test.MultiDimFit.mH125*.root"))
    if args.force or not initial_files:
        run_command(
            ["combineTool.py", "-M", "Impacts", *common, "--doInitialFit"],
            cwd=raw_dir,
            log_path=logs_dir / f"impacts_initial_{label}.log",
            env=env,
        )
        initial_files = list(
            raw_dir.glob("higgsCombine_initialFit_Test.MultiDimFit.mH125*.root")
        )
    if not initial_files:
        raise RuntimeError("Missing impacts initial-fit ROOT output")

    fit_files = list(raw_dir.glob("higgsCombine_paramFit_Test_*.root"))
    fits_complete_marker = raw_dir / "parameter_fits.complete"
    if args.force or not fits_complete_marker.is_file():
        run_command(
            [
                "combineTool.py",
                "-M",
                "Impacts",
                *common,
                "--doFits",
                "--parallel",
                str(max(1, args.workers)),
            ],
            cwd=raw_dir,
            log_path=logs_dir / f"impacts_fits_{label}.log",
            env=env,
        )
        fit_files = list(raw_dir.glob("higgsCombine_paramFit_Test_*.root"))
        fits_complete_marker.write_text(f"{len(fit_files)} parameter-fit ROOT files\n")

    impacts_json = impacts_dir / f"impacts_{label}.json"
    run_command(
        [
            "combineTool.py",
            "-M",
            "Impacts",
            *common,
            "-o",
            str(impacts_json),
        ],
        cwd=raw_dir,
        log_path=logs_dir / f"impacts_collect_{label}.log",
        env=env,
    )
    payload = json.loads(impacts_json.read_text())
    n_parameters = len(payload["params"])
    use_cms_style()
    parameters = sorted_impacts(payload)
    parameters_per_page = 24
    pages = max(1, math.ceil(n_parameters / parameters_per_page))

    leading_parameters = parameters[:20]
    summary_figure = impact_figure(leading_parameters, luminosity_fb)
    save_png_pdf(
        summary_figure,
        impacts_dir / f"impacts_{label}_top20",
    )
    plt.close(summary_figure)
    top_parameters = impact_summary(leading_parameters)

    plot_base = impacts_dir / f"impacts_{label}"
    run_command(
        [
            "plotImpacts.py",
            "-i",
            impacts_json.name,
            "-o",
            plot_base.name,
            "--per-page",
            str(parameters_per_page),
            "--max-pages",
            str(pages),
            "--summary",
            "--height",
            "726",
            "--blind",
            "--cms-label",
            "Work in progress",
        ],
        cwd=impacts_dir,
        log_path=logs_dir / f"impacts_plot_{label}.log",
        env=env,
    )
    poi = payload["POIs"][0]
    summary = {
        "signal": signal["source_name"],
        "label": label,
        "poi": poi["name"],
        "poi_fit": [float(value) for value in poi["fit"]],
        "fit_range": [args.rmin, args.rmax],
        "n_parameters": n_parameters,
        "top_parameters": top_parameters,
        "note": (
            "Blinded background-only Asimov impact fit. The impact fit allows "
            "negative r to avoid a boundary solution; the expected limit "
            "calculation itself constrains r >= 0."
        ),
    }
    write_json(impacts_dir / f"impacts_{label}_summary.json", summary)
    print(f"Wrote {n_parameters} nuisance impacts to {impacts_json}")


if __name__ == "__main__":
    main()
