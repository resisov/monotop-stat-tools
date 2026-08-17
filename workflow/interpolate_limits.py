#!/usr/bin/env python3
"""Interpolate the discrete mass-point limits over the (mphi, mchi) plane."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/codex-monotop-mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import uproot
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy.interpolate import LinearNDInterpolator

from common import DEFAULT_OUTPUT, ensure_directories, write_json
from plotting import cms_label, save_png_pdf, use_cms_style


SURFACES = [
    "expected_minus2",
    "expected_minus1",
    "expected",
    "expected_plus1",
    "expected_plus2",
]

DEFAULT_RELIC_DENSITY_FILE = (
    Path(__file__).resolve().parents[1]
    / "external"
    / "relic_densities"
    / "monotop_vector_nom_relic_density_scan.txt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--step", type=float, default=25.0, help="Grid step in GeV")
    parser.add_argument(
        "--shell-mode",
        choices=["all", "on-shell-only"],
        default="all",
        help="Optionally exclude points with mV <= 2*mchi before interpolation",
    )
    parser.add_argument(
        "--subdirectory",
        default="interpolation",
        help="Output subdirectory below the era output directory",
    )
    parser.add_argument(
        "--relic-density-file",
        type=Path,
        default=DEFAULT_RELIC_DENSITY_FILE,
        help="Nominal vector relic-density scan to overlay",
    )
    parser.add_argument(
        "--relic-density-level",
        type=float,
        default=0.12,
        help="Relic-density contour level",
    )
    parser.add_argument(
        "--plot-ymin",
        type=float,
        default=0.0,
        help="Displayed lower mchi bound in GeV (default: 0)",
    )
    parser.add_argument(
        "--plot-ymax",
        type=float,
        default=1000.0,
        help="Displayed upper mchi bound in GeV (default: 1000)",
    )
    parser.add_argument(
        "--plot-basename",
        default="limit_interpolation",
        help="PNG/PDF basename; use a new name to preserve the default plot",
    )
    return parser.parse_args()


def centers_to_edges(centers: np.ndarray) -> np.ndarray:
    if len(centers) < 2:
        raise ValueError("At least two grid centers are required")
    half = np.diff(centers) / 2.0
    return np.concatenate(
        ([centers[0] - half[0]], centers[:-1] + half, [centers[-1] + half[-1]])
    )


def load_relic_density(path: Path) -> dict[str, np.ndarray | str]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Relic-density scan not found: {path}")
    values = np.loadtxt(path, delimiter="\t", usecols=(1, 2, 3))
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"Unexpected relic-density scan format: {path}")
    valid = np.all(np.isfinite(values), axis=1) & (values[:, 2] > 0.0)
    values = values[valid]
    return {
        "mphi": values[:, 0],
        "mchi": values[:, 1],
        "density": values[:, 2],
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def draw_relic_density_contour(
    axis: plt.Axes,
    relic: dict[str, np.ndarray | str],
    level: float,
) -> int:
    mphi = np.asarray(relic["mphi"], dtype=float)
    mchi = np.asarray(relic["mchi"], dtype=float)
    density = np.asarray(relic["density"], dtype=float)
    contour_count = 0
    # Triangulate the two shell regimes independently.  This follows the Run-2
    # implementation and prevents artificial contour segments across mV=2*mchi.
    for mask in (mphi >= 2.0 * mchi, mphi < 2.0 * mchi):
        if np.count_nonzero(mask) < 3:
            continue
        subset = density[mask]
        if not (np.nanmin(subset) <= level <= np.nanmax(subset)):
            continue
        contour = axis.tricontour(
            mphi[mask],
            mchi[mask],
            subset,
            levels=[level],
            colors=["#666666"],
            linewidths=2.4,
            linestyles="-",
            zorder=8,
        )
        segments = [segment for segment in contour.allsegs[0] if len(segment) > 1]
        contour_count += len(segments)
        # Match the Run-2 presentation with a narrow, unfilled hatched strip
        # along the physical relic-density contour.
        if segments:
            vertices = segments[0]
            dx = np.diff(vertices[:, 0])
            dy = np.diff(vertices[:, 1])
            length = np.hypot(dx, dy)
            valid_length = np.where(length > 0.0, length, 1.0)
            shifted_y = vertices[:-1, 1] + 20.0 * dx / valid_length
            axis.fill_between(
                vertices[:-1, 0],
                vertices[:-1, 1],
                shifted_y,
                facecolor="none",
                edgecolor="#777777",
                hatch="///",
                linewidth=0.0,
                zorder=7,
            )
    return contour_count


def main() -> None:
    args = parse_args()
    if args.plot_ymin >= args.plot_ymax:
        raise ValueError("--plot-ymin must be smaller than --plot-ymax")
    if Path(args.plot_basename).name != args.plot_basename:
        raise ValueError("--plot-basename must be a filename without directories")
    output = args.output.resolve()
    interpolation_dir = output / args.subdirectory
    ensure_directories([interpolation_dir])
    manifest = json.loads((output / "manifest.json").read_text())
    luminosity_fb = float(manifest["luminosity_fb"])
    relic = load_relic_density(args.relic_density_file)
    all_rows = json.loads((output / "limits" / "limits.json").read_text())
    rows = (
        [
            row
            for row in all_rows
            if float(row["mphi"]) > 2.0 * float(row["mchi"])
        ]
        if args.shell_mode == "on-shell-only"
        else all_rows
    )
    if len(rows) < 3:
        raise RuntimeError(
            f"Need at least three points for interpolation; found {len(rows)}"
        )
    points = np.asarray([[row["mphi"], row["mchi"]] for row in rows], dtype=float)

    mphi_grid = np.arange(points[:, 0].min(), points[:, 0].max() + 0.5 * args.step, args.step)
    mchi_grid = np.arange(points[:, 1].min(), points[:, 1].max() + 0.5 * args.step, args.step)
    xx, yy = np.meshgrid(mphi_grid, mchi_grid, indexing="ij")
    surfaces: dict[str, np.ndarray] = {}
    for surface in SURFACES:
        values = np.asarray([row[surface] for row in rows], dtype=float)
        valid = np.isfinite(values) & (values > 0.0)
        interpolator = LinearNDInterpolator(
            points[valid],
            np.log10(values[valid]),
            fill_value=np.nan,
        )
        surfaces[surface] = np.power(10.0, interpolator(xx, yy))

    np.savez_compressed(
        interpolation_dir / "limit_surfaces.npz",
        mphi=mphi_grid,
        mchi=mchi_grid,
        **surfaces,
    )
    with uproot.recreate(interpolation_dir / "limit_surfaces.root") as root_file:
        x_edges = centers_to_edges(mphi_grid)
        y_edges = centers_to_edges(mchi_grid)
        for name, values in surfaces.items():
            root_file[name] = (values, x_edges, y_edges)

    csv_path = interpolation_dir / "limit_surfaces.csv"
    with csv_path.open("w", newline="") as handle:
        fields = ["mphi", "mchi", *SURFACES]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for ix, mphi in enumerate(mphi_grid):
            for iy, mchi in enumerate(mchi_grid):
                if not np.isfinite(surfaces["expected"][ix, iy]):
                    continue
                writer.writerow(
                    {
                        "mphi": mphi,
                        "mchi": mchi,
                        **{name: surfaces[name][ix, iy] for name in SURFACES},
                    }
                )

    expected = surfaces["expected"]
    expected_minus1 = surfaces["expected_minus1"]
    expected_plus1 = surfaces["expected_plus1"]
    finite = expected[np.isfinite(expected) & (expected > 0.0)]
    vmin = max(float(np.nanpercentile(finite, 2)), 1e-4)
    vmax = max(float(np.nanpercentile(finite, 98)), vmin * 10.0)
    use_cms_style()
    fig, axis = plt.subplots(figsize=(12.0, 10.0))
    mesh = axis.pcolormesh(
        mphi_grid,
        mchi_grid,
        expected.T,
        shading="auto",
        cmap="viridis",
        norm=LogNorm(vmin=vmin, vmax=vmax),
    )
    one_sigma_band = np.where(
        (expected_minus1 <= 1.0) & (expected_plus1 >= 1.0),
        1.0,
        np.nan,
    )
    if np.any(np.isfinite(one_sigma_band)):
        axis.contourf(
            mphi_grid,
            mchi_grid,
            one_sigma_band.T,
            levels=[0.5, 1.5],
            colors=["#d95f5f"],
            alpha=0.28,
        )
    for surface in (expected_minus1, expected_plus1):
        finite_surface = surface[np.isfinite(surface)]
        if len(finite_surface) and np.nanmin(finite_surface) <= 1.0 <= np.nanmax(
            finite_surface
        ):
            axis.contour(
                mphi_grid,
                mchi_grid,
                surface.T,
                levels=[1.0],
                colors=["#b2182b"],
                linewidths=1.8,
                linestyles="--",
            )
    if np.nanmin(expected) <= 1.0 <= np.nanmax(expected):
        axis.contour(
            mphi_grid,
            mchi_grid,
            expected.T,
            levels=[1.0],
            colors=["black"],
            linewidths=2.2,
        )

    relic_contour_segments = draw_relic_density_contour(
        axis,
        relic,
        args.relic_density_level,
    )
    if relic_contour_segments == 0:
        raise RuntimeError(
            f"No relic-density contour found at Omega*h^2={args.relic_density_level}"
        )

    shell_mediator = np.linspace(mphi_grid.min(), mphi_grid.max(), 500)
    shell_dark_matter = 0.5 * shell_mediator
    shell_mask = (shell_dark_matter >= mchi_grid.min()) & (
        shell_dark_matter <= mchi_grid.max()
    )
    axis.plot(
        shell_mediator[shell_mask],
        shell_dark_matter[shell_mask],
        color="black",
        linestyle=":",
        linewidth=2.0,
    )
    colorbar = fig.colorbar(mesh, ax=axis)
    colorbar.set_label("Expected 95% CL upper limit on r")
    axis.set_xlabel(r"$m_V$ [GeV]")
    axis.set_ylabel(r"$m_{\chi}$ [GeV]")
    legend_handles = [
        Line2D([0], [0], color="black", linewidth=2.2, label="Expected $r=1$"),
        Patch(
            facecolor="#d95f5f",
            edgecolor="#b2182b",
            linestyle="--",
            alpha=0.5,
            label=r"Expected $\pm1\sigma$",
        ),
        Line2D(
            [0],
            [0],
            color="#666666",
            linestyle="-",
            linewidth=2.4,
            label=rf"Relic density = {args.relic_density_level:g}",
        ),
        Line2D(
            [0],
            [0],
            color="black",
            linestyle=":",
            linewidth=2.0,
            label=r"$m_V=2m_\chi$",
        ),
    ]
    axis.legend(
        handles=legend_handles,
        loc="upper left",
        fontsize=18,
    )
    axis.set_xlim(0.0, 2000.0)
    axis.set_ylim(args.plot_ymin, args.plot_ymax)
    axis.grid(alpha=0.15)
    cms_label(axis, luminosity_fb)
    fig.tight_layout()
    save_png_pdf(fig, interpolation_dir / args.plot_basename)
    plt.close(fig)

    summary = {
        "method": "piecewise-linear interpolation of log10(r95) inside the convex hull",
        "shell_mode": args.shell_mode,
        "step_gev": args.step,
        "n_all_input_points": len(all_rows),
        "n_input_points": len(rows),
        "n_finite_grid_points": int(np.isfinite(expected).sum()),
        "mphi_range_gev": [float(mphi_grid.min()), float(mphi_grid.max())],
        "mchi_range_gev": [float(mchi_grid.min()), float(mchi_grid.max())],
        "displayed_mphi_range_gev": [0.0, 2000.0],
        "displayed_mchi_range_gev": [args.plot_ymin, args.plot_ymax],
        "plot_basename": args.plot_basename,
        "extrapolation": "none",
        "relic_density": {
            "source": str(relic["path"]),
            "sha256": str(relic["sha256"]),
            "columns": ["mV", "mchi", "Omega_h2"],
            "constraint": float(args.relic_density_level),
            "n_input_points": int(len(np.asarray(relic["mphi"]))),
            "n_contour_segments": int(relic_contour_segments),
            "shell_triangulation": "on-shell and off-shell subsets treated independently",
        },
    }
    summary_filename = (
        "interpolation_summary.json"
        if args.plot_basename == "limit_interpolation"
        else f"{args.plot_basename}_summary.json"
    )
    write_json(interpolation_dir / summary_filename, summary)
    print(f"Wrote interpolated surfaces to {interpolation_dir}")


if __name__ == "__main__":
    main()
