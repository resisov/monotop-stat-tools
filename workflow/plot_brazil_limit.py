#!/usr/bin/env python3
"""Plot a blinded one-dimensional expected-limit slice at fixed dark-matter mass."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/codex-monotop-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
from scipy.interpolate import LinearNDInterpolator

from common import DEFAULT_OUTPUT, ensure_directories, write_json
from plotting import cms_label, save_png_pdf, use_cms_style


SURFACES = (
    "expected_minus2",
    "expected_minus1",
    "expected",
    "expected_plus1",
    "expected_plus2",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mx", type=float, default=200.0, help="Fixed mX in GeV")
    parser.add_argument("--step", type=float, default=25.0, help="mV grid step in GeV")
    parser.add_argument("--xmin", type=float, default=500.0, help="Displayed mV minimum")
    parser.add_argument("--xmax", type=float, default=2000.0, help="Displayed mV maximum")
    parser.add_argument(
        "--shell-mode",
        choices=("all", "on-shell-only"),
        default="on-shell-only",
        help="Use all points or only mV > 2*mX points",
    )
    parser.add_argument(
        "--subdirectory",
        default="interpolation",
        help="Output subdirectory below the era output directory",
    )
    return parser.parse_args()


def interpolate_slice(
    rows: list[dict[str, object]],
    mx: float,
    step: float,
    xmax: float,
    shell_mode: str,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    if shell_mode == "on-shell-only":
        rows = [
            row
            for row in rows
            if float(row["mphi"]) > 2.0 * float(row["mchi"])
        ]
    points = np.asarray([[row["mphi"], row["mchi"]] for row in rows], dtype=float)
    mv = np.arange(0.0, xmax + 0.5 * step, step)
    evaluation_points = np.column_stack((mv, np.full_like(mv, mx)))
    surfaces: dict[str, np.ndarray] = {}

    for name in SURFACES:
        values = np.asarray([row[name] for row in rows], dtype=float)
        valid = np.isfinite(values) & (values > 0.0)
        interpolator = LinearNDInterpolator(
            points[valid], np.log10(values[valid]), fill_value=np.nan
        )
        surfaces[name] = np.power(10.0, interpolator(evaluation_points))

    finite = np.logical_and.reduce([np.isfinite(surfaces[name]) for name in SURFACES])
    if shell_mode == "on-shell-only":
        finite &= mv > 2.0 * mx
    return mv[finite], {name: values[finite] for name, values in surfaces.items()}


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    plot_dir = output / args.subdirectory
    ensure_directories([plot_dir])

    manifest = json.loads((output / "manifest.json").read_text())
    luminosity_fb = float(manifest["luminosity_fb"])
    rows = json.loads((output / "limits" / "limits.json").read_text())
    mv, surfaces = interpolate_slice(
        rows, args.mx, args.step, args.xmax, args.shell_mode
    )
    if len(mv) < 2:
        raise RuntimeError(f"No interpolated limit slice is available at mX={args.mx:g} GeV")

    stem = f"limit_brazil_mx{args.mx:g}".replace(".", "p")
    csv_path = plot_dir / f"{stem}.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["mV", "mX", *SURFACES])
        writer.writeheader()
        for index, mediator_mass in enumerate(mv):
            writer.writerow(
                {
                    "mV": float(mediator_mass),
                    "mX": float(args.mx),
                    **{name: float(surfaces[name][index]) for name in SURFACES},
                }
            )

    use_cms_style()
    figure, axis = plt.subplots(figsize=(11.0, 11.0))
    axis.fill_between(
        mv,
        surfaces["expected_minus2"],
        surfaces["expected_plus2"],
        color="#F5D547",
        linewidth=0.0,
        label=r"Expected $\pm2\sigma$",
        zorder=1,
    )
    axis.fill_between(
        mv,
        surfaces["expected_minus1"],
        surfaces["expected_plus1"],
        color="#62B55A",
        linewidth=0.0,
        label=r"Expected $\pm1\sigma$",
        zorder=2,
    )
    axis.plot(
        mv,
        surfaces["expected"],
        color="black",
        linewidth=2.8,
        linestyle="--",
        zorder=3,
    )
    axis.axhline(1.0, color="black", linewidth=2.0, linestyle="-", zorder=4)
    shell_boundary = 2.0 * args.mx
    if args.xmin <= shell_boundary <= args.xmax:
        axis.axvline(
            shell_boundary,
            color="black",
            linewidth=2.0,
            linestyle=":",
            zorder=4,
        )

    positive = np.concatenate([surfaces["expected_minus2"], surfaces["expected_plus2"]])
    positive = positive[np.isfinite(positive) & (positive > 0.0)]
    ymin = 10.0 ** np.floor(np.log10(float(positive.min())))
    ymax = 10.0 ** np.ceil(np.log10(float(positive.max())))
    if ymax <= ymin:
        ymax = ymin * 10.0

    axis.set_yscale("log")
    axis.set_xlim(args.xmin, args.xmax)
    axis.set_ylim(ymin, ymax)
    axis.set_xlabel(r"$m_V$ [GeV]")
    axis.set_ylabel("Expected 95% CL upper limit on r")
    axis.grid(which="both", alpha=0.15)
    legend_handles = [
            Line2D(
                [0],
                [0],
                color="black",
                linewidth=2.8,
                linestyle="--",
                label=rf"Median expected ($m_X={args.mx:g}$ GeV)",
            ),
            Patch(facecolor="#62B55A", edgecolor="none", label=r"Expected $\pm1\sigma$"),
            Patch(facecolor="#F5D547", edgecolor="none", label=r"Expected $\pm2\sigma$"),
            Line2D([0], [0], color="black", linewidth=2.0, label=r"$r=1$"),
    ]
    if args.xmin <= shell_boundary <= args.xmax:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                color="black",
                linewidth=2.0,
                linestyle=":",
                label=r"$m_V=2m_X$",
            )
        )
    axis.legend(
        handles=legend_handles,
        loc="upper right",
        fontsize=18,
        frameon=False,
    )
    cms_label(axis, luminosity_fb)
    figure.tight_layout()
    save_png_pdf(figure, plot_dir / stem)
    plt.close(figure)

    write_json(
        plot_dir / f"{stem}.json",
        {
            "blinded": True,
            "fixed_mX_gev": float(args.mx),
            "shell_mode": args.shell_mode,
            "method": "piecewise-linear interpolation of log10(r95) inside the input convex hull",
            "input": str((output / "limits" / "limits.json").relative_to(output)),
            "mV_step_gev": float(args.step),
            "displayed_mV_range_gev": [float(args.xmin), float(args.xmax)],
            "finite_mV_range_gev": [float(mv.min()), float(mv.max())],
            "n_finite_points": int(len(mv)),
            "observed_limit_drawn": False,
        },
    )
    print(f"Wrote blinded mX={args.mx:g} GeV Brazilian plot to {plot_dir / stem}")


if __name__ == "__main__":
    main()
