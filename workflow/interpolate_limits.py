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
import matplotlib.patheffects as path_effects
import mplhep as hep
import numpy as np
import uproot
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D

from common import DEFAULT_OUTPUT, ensure_directories, write_json
from limit_interpolation import (
    SHELL_MODES,
    coordinate_system,
    domain_coordinate_systems,
    interpolate_log_surface,
)
from plotting import MODEL_LABEL, cms_label, save_png_pdf, use_cms_style


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
DEFAULT_RUN2_OBSERVED_CONTOUR = (
    Path(__file__).resolve().parents[1]
    / "external"
    / "run2"
    / "cms_sus_23_004_vector_observed.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--step", type=float, default=25.0, help="Grid step in GeV")
    parser.add_argument(
        "--shell-mode",
        choices=SHELL_MODES,
        default="all",
        help=(
            "Use separate threshold-aware on/off-shell interpolation domains, "
            "or select one domain only"
        ),
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
        "--run2-observed-contour",
        type=Path,
        default=None,
        help=(
            "Optional ordered mV,mX CSV for a Run-2 observed exclusion overlay; "
            f"the matching nominal CMS contour is {DEFAULT_RUN2_OBSERVED_CONTOUR}"
        ),
    )
    parser.add_argument(
        "--plot-xmin",
        type=float,
        default=200.0,
        help="Displayed lower mediator-mass bound on the x axis in GeV (default: 200)",
    )
    parser.add_argument(
        "--plot-xmax",
        type=float,
        default=2500.0,
        help="Displayed upper mediator-mass bound on the x axis in GeV (default: 2500)",
    )
    parser.add_argument(
        "--plot-ymin",
        type=float,
        default=50.0,
        help="Displayed lower mchi bound on the y axis in GeV (default: 50)",
    )
    parser.add_argument(
        "--plot-ymax",
        type=float,
        default=1250.0,
        help="Displayed upper mchi bound on the y axis in GeV (default: 1250)",
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


def load_observed_contour(path: Path) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Observed contour not found: {path}")
    values = np.genfromtxt(path, delimiter=",", names=True)
    if values.dtype.names != ("mV_GeV", "mX_GeV"):
        raise ValueError(
            "Observed contour must contain exactly mV_GeV,mX_GeV columns: "
            f"{path}"
        )
    mphi = np.atleast_1d(np.asarray(values["mV_GeV"], dtype=float))
    mchi = np.atleast_1d(np.asarray(values["mX_GeV"], dtype=float))
    valid = np.isfinite(mphi) & np.isfinite(mchi)
    mphi = mphi[valid]
    mchi = mchi[valid]
    if len(mphi) < 2:
        raise ValueError(f"Observed contour has fewer than two finite points: {path}")
    metadata_path = path.with_suffix(".json")
    metadata = (
        json.loads(metadata_path.read_text()) if metadata_path.is_file() else None
    )
    return {
        "mphi": mphi,
        "mchi": mchi,
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "metadata": metadata,
    }


def draw_relic_density_contour(
    axis: plt.Axes,
    relic: dict[str, np.ndarray | str],
    level: float,
    shell_mode: str,
) -> int:
    mphi = np.asarray(relic["mphi"], dtype=float)
    mchi = np.asarray(relic["mchi"], dtype=float)
    density = np.asarray(relic["density"], dtype=float)
    contour_count = 0
    # Triangulate the two shell regimes independently.  This follows the Run-2
    # implementation and prevents artificial contour segments across mV=2*mchi.
    masks = []
    if shell_mode in ("all", "on-shell-only"):
        masks.append(mphi > 2.0 * mchi)
    if shell_mode in ("all", "off-shell-only"):
        masks.append(mphi < 2.0 * mchi)
    for mask in masks:
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
    if args.plot_xmin >= args.plot_xmax:
        raise ValueError("--plot-xmin must be smaller than --plot-xmax")
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
    run2_observed = (
        load_observed_contour(args.run2_observed_contour)
        if args.run2_observed_contour is not None
        else None
    )
    draw_run2_observed = (
        run2_observed is not None and args.shell_mode != "off-shell-only"
    )
    all_rows = json.loads((output / "limits" / "limits.json").read_text())
    if args.shell_mode == "on-shell-only":
        rows = [
            row
            for row in all_rows
            if float(row["mphi"]) > 2.0 * float(row["mchi"])
        ]
    elif args.shell_mode == "off-shell-only":
        rows = [
            row
            for row in all_rows
            if float(row["mphi"]) < 2.0 * float(row["mchi"])
        ]
    else:
        rows = all_rows
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
        surfaces[surface] = interpolate_log_surface(
            points[:, 0],
            points[:, 1],
            values,
            xx,
            yy,
            shell_mode=args.shell_mode,
        )

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
    colorbar_log10_limits = (-1.5, 1.5)
    use_cms_style()
    fig, axis = plt.subplots(figsize=(12.0, 10.0))
    mesh = axis.pcolormesh(
        mphi_grid,
        mchi_grid,
        np.log10(expected.T),
        shading="auto",
        cmap="viridis_r",
        norm=Normalize(
            vmin=colorbar_log10_limits[0],
            vmax=colorbar_log10_limits[1],
            clip=True,
        ),
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
                colors=["#ff0000"],
                linewidths=2.0,
                linestyles="--",
            )
    if np.nanmin(expected) <= 1.0 <= np.nanmax(expected):
        axis.contour(
            mphi_grid,
            mchi_grid,
            expected.T,
            levels=[1.0],
            colors=["#ff0000"],
            linewidths=2.4,
            linestyles="-",
        )

    run2_color = "#00a6ff"
    if draw_run2_observed:
        run2_line = axis.plot(
            np.asarray(run2_observed["mphi"], dtype=float),
            np.asarray(run2_observed["mchi"], dtype=float),
            color=run2_color,
            linewidth=3.0,
            linestyle="-",
            zorder=14,
        )[0]
        run2_line.set_path_effects(
            [
                path_effects.Stroke(linewidth=4.8, foreground="white"),
                path_effects.Normal(),
            ]
        )

    relic_contour_segments = draw_relic_density_contour(
        axis,
        relic,
        args.relic_density_level,
        args.shell_mode,
    )
    if relic_contour_segments == 0 and args.shell_mode != "off-shell-only":
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
    colorbar.set_label(r"$\log_{10}$(expected 95% CL upper limit on $r$)")
    axis.set_xlabel(r"$m_V$ [GeV]")
    axis.set_ylabel(r"$m_{\chi}$ [GeV]")
    legend_handles = [
        Line2D(
            [0],
            [0],
            color="#ff0000",
            linewidth=2.4,
            linestyle="-",
            label="Expected $r=1$",
        ),
        Line2D(
            [0],
            [0],
            color="#ff0000",
            linewidth=2.0,
            linestyle="--",
            label=r"Expected $\pm1\sigma$",
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
    if draw_run2_observed:
        legend_handles.insert(
            2,
            Line2D(
                [0],
                [0],
                color=run2_color,
                linewidth=3.0,
                linestyle="-",
                label=r"Run 2 observed (138 fb$^{-1}$)",
            ),
        )
    if relic_contour_segments > 0:
        legend_handles.insert(
            2,
            Line2D(
                [0],
                [0],
                color="#666666",
                linestyle="-",
                linewidth=2.4,
                label=rf"$\Omega_{{\mathrm{{nbm}}}}h^2 = {args.relic_density_level:g}$",
            ),
        )
    legend = axis.legend(
        handles=legend_handles,
        loc="upper left",
        fontsize=18,
        title=MODEL_LABEL,
        title_fontsize=20,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        framealpha=1.0,
        borderpad=0.45,
        labelspacing=0.32,
        handlelength=1.9,
        handletextpad=0.55,
        borderaxespad=0.55,
    )
    legend.set_zorder(30)
    axis.set_xlim(args.plot_xmin, args.plot_xmax)
    axis.set_ylim(args.plot_ymin, args.plot_ymax)
    axis.grid(alpha=0.15)
    cms_label(axis, luminosity_fb)
    fig.tight_layout()
    save_png_pdf(fig, interpolation_dir / args.plot_basename)
    plt.close(fig)

    interpolation_axes = coordinate_system(args.shell_mode)
    domain_systems = domain_coordinate_systems(args.shell_mode)
    summary = {
        "method": (
            "continuous signed-threshold interpolation of log10(r95) inside the "
            "transformed convex hull"
            if args.shell_mode == "all"
            else "threshold-aware piecewise-linear interpolation of log10(r95) "
            "inside the transformed convex hull"
        ),
        "coordinate_system": list(interpolation_axes),
        "domain_coordinate_systems": domain_systems,
        "coordinate_rescaling": True,
        "beta_chi_definition": (
            "sqrt(1 - (2*mX/mV)^2) for the strict mV > 2*mX domain"
            if args.shell_mode in ("all", "on-shell-only")
            else None
        ),
        "kappa_chi_definition": (
            "sqrt((2*mX/mV)^2 - 1) for the strict mV < 2*mX domain"
            if args.shell_mode in ("all", "off-shell-only")
            else None
        ),
        "threshold_stitching": (
            "solid C0 connection at signed_shell_coordinate = 0"
            if args.shell_mode == "all"
            else "not applicable to a single shell domain"
        ),
        "contour_style": {
            "expected": {
                "color": "#ff0000",
                "linestyle": "solid",
                "linewidth": 2.4,
            },
            "expected_pm1sigma": {
                "color": "#ff0000",
                "linestyle": "dashed",
                "linewidth": 2.0,
            },
            "filled_uncertainty_band": False,
        },
        "colorbar_quantity": "log10(r)",
        "colorbar_limits_log10_r": list(colorbar_log10_limits),
        "colorbar_colormap": "viridis_r",
        "signal_model": {
            "mediator": "vector",
            "g_q": 0.25,
            "g_DM": 1.0,
        },
        "run2_observed_overlay": {
            "requested": run2_observed is not None,
            "drawn": bool(draw_run2_observed),
            "reason_not_drawn": (
                "Run-2 result is on-shell only"
                if run2_observed is not None and not draw_run2_observed
                else None
            ),
            "source": (
                str(run2_observed["path"])
                if run2_observed is not None
                else None
            ),
            "sha256": (
                str(run2_observed["sha256"])
                if run2_observed is not None
                else None
            ),
            "n_points": (
                int(len(np.asarray(run2_observed["mphi"])))
                if run2_observed is not None
                else 0
            ),
            "color": run2_color if draw_run2_observed else None,
            "linestyle": "solid" if draw_run2_observed else None,
            "label": (
                "CMS Run 2 observed (138 fb^-1)" if draw_run2_observed else None
            ),
            "metadata": (
                run2_observed["metadata"]
                if run2_observed is not None
                else None
            ),
        },
        "shell_mode": args.shell_mode,
        "step_gev": args.step,
        "n_all_input_points": len(all_rows),
        "n_input_points": len(rows),
        "n_finite_grid_points": int(np.isfinite(expected).sum()),
        "mphi_range_gev": [float(mphi_grid.min()), float(mphi_grid.max())],
        "mchi_range_gev": [float(mchi_grid.min()), float(mchi_grid.max())],
        "plot_axis_order": ["mV", "mX"],
        "displayed_mphi_range_gev": [args.plot_xmin, args.plot_xmax],
        "displayed_mchi_range_gev": [args.plot_ymin, args.plot_ymax],
        "plot_basename": args.plot_basename,
        "extrapolation": "none",
        "relic_density": {
            "source": str(relic["path"]),
            "sha256": str(relic["sha256"]),
            "columns": ["mV", "mchi", "Omega_h2"],
            "constraint": float(args.relic_density_level),
            "legend_label": f"Omega_nbm h^2 = {args.relic_density_level:g}",
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
