#!/usr/bin/env python3
"""Plot Run-2-style transfer factors separately for top pass and top fail."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from plotting import cms_label, save_png_pdf, use_cms_style

import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
from matplotlib.ticker import MaxNLocator

from common import DEFAULT_OUTPUT, ensure_directories, write_json


TF_GROUPS: dict[str, list[dict[str, Any]]] = {
    "z": [
        {
            "label": r"$Z(\mu\mu)_{\mathrm{CR}}\,/\,Z(\nu\bar{\nu})_{\mathrm{SR}}$",
            "numerator": ("zmcr", "zll"),
            "denominator": ("sr", "zjets"),
        },
        {
            "label": r"$Z(ee)_{\mathrm{CR}}\,/\,Z(\nu\bar{\nu})_{\mathrm{SR}}$",
            "numerator": ("zecr", "zll"),
            "denominator": ("sr", "zjets"),
        },
    ],
    "w": [
        {
            "label": r"$W(\mu\nu)_{\mathrm{CR}}\,/\,Z(\nu\bar{\nu})_{\mathrm{SR}}$",
            "numerator": ("wmcr", "wjets"),
            "denominator": ("sr", "zjets"),
        },
        {
            "label": r"$W(e\nu)_{\mathrm{CR}}\,/\,Z(\nu\bar{\nu})_{\mathrm{SR}}$",
            "numerator": ("wecr", "wjets"),
            "denominator": ("sr", "zjets"),
        },
        {
            "label": r"$W(\ell\nu)_{\mathrm{SR}}\,/\,Z(\nu\bar{\nu})_{\mathrm{SR}}$",
            "numerator": ("sr", "wjets"),
            "denominator": ("sr", "zjets"),
        },
    ],
    "gamma": [
        {
            "label": r"$\gamma_{\mathrm{CR}}\,/\,Z(\nu\bar{\nu})_{\mathrm{SR}}$",
            "numerator": ("gcr", "gjets"),
            "denominator": ("sr", "zjets"),
        },
    ],
    "top": [
        {
            "label": r"$\mathrm{Top}_{\mathrm{CR}(t\mu)}\,/\,\mathrm{Top}_{\mathrm{SR}}\ (\mathrm{TT+ST})$",
            "numerator": ("tmcr", "top"),
            "denominator": ("sr", "top"),
        },
        {
            "label": r"$\mathrm{Top}_{\mathrm{CR}(te)}\,/\,\mathrm{Top}_{\mathrm{SR}}\ (\mathrm{TT+ST})$",
            "numerator": ("tecr", "top"),
            "denominator": ("sr", "top"),
        },
        {
            "label": r"$\mathrm{Top}_{\mathrm{CR}(W\mu)}\,/\,\mathrm{Top}_{\mathrm{SR}}\ (\mathrm{TT+ST})$",
            "numerator": ("wmcr", "top"),
            "denominator": ("sr", "top"),
        },
        {
            "label": r"$\mathrm{Top}_{\mathrm{CR}(We)}\,/\,\mathrm{Top}_{\mathrm{SR}}\ (\mathrm{TT+ST})$",
            "numerator": ("wecr", "top"),
            "denominator": ("sr", "top"),
        },
    ],
}

SERIES_COLORS = ["#2563eb", "#dc2626", "#d97706", "#7c3aed"]
SERIES_MARKERS = ["s", "o", "^", "D"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_yields(path: Path) -> tuple[
    dict[tuple[str, str, float, float, str], tuple[float, float]],
    dict[str, list[tuple[float, float]]],
]:
    yield_map: dict[tuple[str, str, float, float, str], tuple[float, float]] = {}
    recoil_bins: dict[str, set[tuple[float, float]]] = {"pass": set(), "fail": set()}
    with path.open() as handle:
        for row in csv.DictReader(handle):
            category = row["top_category"]
            low = float(row["recoil_low_gev"])
            high = float(row["recoil_high_gev"])
            key = (row["region"], category, low, high, row["process"])
            yield_map[key] = (float(row["yield"]), float(row["mc_variance"]))
            if row["region"] == "sr" and row["process"] == "zjets":
                recoil_bins[category].add((low, high))
    return yield_map, {
        category: sorted(bins)
        for category, bins in recoil_bins.items()
    }


def calculate_ratio(
    yield_map: dict[tuple[str, str, float, float, str], tuple[float, float]],
    category: str,
    low: float,
    high: float,
    definition: dict[str, Any],
) -> tuple[float, float]:
    numerator_region, numerator_process = definition["numerator"]
    denominator_region, denominator_process = definition["denominator"]
    numerator, numerator_variance = yield_map[
        (numerator_region, category, low, high, numerator_process)
    ]
    denominator, denominator_variance = yield_map[
        (denominator_region, category, low, high, denominator_process)
    ]
    if numerator <= 0.0 or denominator <= 0.0:
        raise ValueError(
            "Cannot calculate a positive transfer factor for "
            f"{definition['label']} in {category}, {low:g}-{high:g} GeV"
        )
    ratio = numerator / denominator
    relative_variance = (
        numerator_variance / numerator**2
        + denominator_variance / denominator**2
    )
    return ratio, ratio * math.sqrt(max(relative_variance, 0.0))


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    plot_dir = output / "plots" / "transfer_factors"
    ensure_directories([plot_dir])
    use_cms_style()
    manifest = json.loads((output / "manifest.json").read_text())
    luminosity_fb = float(manifest["luminosity_fb"])
    yield_map, recoil_bins = load_yields(output / "validation" / "yields.csv")

    products: list[dict[str, Any]] = []
    for category in ("pass", "fail"):
        bins = recoil_bins[category]
        if not bins:
            continue
        edges = np.asarray([low for low, _ in bins] + [bins[-1][1]], dtype=float)

        for group_name, definitions in TF_GROUPS.items():
            figure, axis = plt.subplots(figsize=(11.0, 11.0))
            plotted_values: list[float] = []
            plotted_errors: list[float] = []

            for index, definition in enumerate(definitions):
                ratio_and_error = [
                    calculate_ratio(yield_map, category, low, high, definition)
                    for low, high in bins
                ]
                values = np.asarray([item[0] for item in ratio_and_error], dtype=float)
                errors = np.asarray([item[1] for item in ratio_and_error], dtype=float)
                color = SERIES_COLORS[index]
                marker = SERIES_MARKERS[index]

                hep.histplot(
                    values,
                    bins=edges,
                    histtype="step",
                    color=color,
                    linewidth=1.5,
                    alpha=0.55,
                    label="_nolegend_",
                    ax=axis,
                )
                hep.histplot(
                    values,
                    bins=edges,
                    xerr=True,
                    yerr=errors,
                    histtype="errorbar",
                    color=color,
                    marker=marker,
                    markersize=7,
                    capsize=2.5,
                    label=definition["label"],
                    zorder=3,
                    ax=axis,
                )
                plotted_values.extend(values.tolist())
                plotted_errors.extend(errors.tolist())

            values_array = np.asarray(plotted_values, dtype=float)
            errors_array = np.asarray(plotted_errors, dtype=float)
            lower = float(np.min(values_array - errors_array))
            upper = float(np.max(values_array + errors_array))
            span = upper - lower
            if span <= 0.0:
                span = max(abs(upper), 1.0) * 0.1
            axis.set_ylim(max(0.0, lower - 0.12 * span), upper + 0.20 * span)
            axis.set_xlim(edges[0], edges[-1])
            axis.set_xlabel(r"$U_T$ [GeV]")
            axis.set_ylabel("Transfer factor")
            axis.ticklabel_format(axis="y", style="plain", useOffset=False)
            axis.yaxis.set_major_locator(MaxNLocator(nbins=7))
            axis.grid(axis="y", alpha=0.22, linestyle=":", linewidth=1.0)
            axis.legend(
                loc="best",
                fontsize=20 if len(definitions) == 4 else 22,
                markerscale=1.15,
                frameon=False,
            )
            cms_label(axis, luminosity_fb)
            figure.tight_layout()

            base_path = plot_dir / f"tf_{group_name}_{category}"
            save_png_pdf(figure, base_path)
            plt.close(figure)
            products.append(
                {
                    "group": group_name,
                    "top_category": category,
                    "definition": "numerator MC yield / denominator MC yield",
                    "ratios": [
                        {
                            "label": definition["label"],
                            "numerator_region": definition["numerator"][0],
                            "numerator_process": definition["numerator"][1],
                            "denominator_region": definition["denominator"][0],
                            "denominator_process": definition["denominator"][1],
                        }
                        for definition in definitions
                    ],
                    "png": str(base_path.with_suffix(".png").relative_to(output)),
                    "pdf": str(base_path.with_suffix(".pdf").relative_to(output)),
                }
            )

    write_json(plot_dir / "manifest.json", products)
    print(
        f"Wrote {len(products)} Run-2-style TF plots with separate top pass/fail "
        f"to {plot_dir}"
    )


if __name__ == "__main__":
    main()
