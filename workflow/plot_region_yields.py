#!/usr/bin/env python3
"""Plot pre-fit yields for every SR/CR and top pass/fail category."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from plotting import cms_label, save_png_pdf, use_cms_style

import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np

from common import DEFAULT_OUTPUT, ensure_directories, write_json


REGIONS = ["sr", "wmcr", "wecr", "tmcr", "tecr", "gcr", "zmcr", "zecr"]
BACKGROUNDS = ["qcd", "diboson", "top", "wjets", "zll", "gjets", "zjets"]
BACKGROUND_LABELS = {
    "qcd": "QCD",
    "diboson": "Diboson",
    "top": r"$t\bar{t}$ + single top",
    "wjets": r"$W$+jets",
    "zll": r"$Z/\gamma^*(\ell\ell)$+jets",
    "gjets": r"$\gamma$+jets",
    "zjets": r"$Z(\nu\nu)$+jets",
}
BACKGROUND_COLORS = {
    "qcd": "#f4a582",
    "diboson": "#92c5de",
    "top": "#b2182b",
    "wjets": "#67a9cf",
    "zll": "#d1e5f0",
    "gjets": "#fddbc7",
    "zjets": "#2166ac",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    plot_dir = output / "plots" / "regions"
    ensure_directories([plot_dir])
    use_cms_style()

    with (output / "validation" / "yields.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    manifest = json.loads((output / "manifest.json").read_text())
    luminosity_fb = float(manifest["luminosity_fb"])
    data_availability = manifest.get(
        "data_available_by_region",
        {region: True for region in REGIONS},
    )
    benchmark_source = str(manifest["benchmark_signal"])
    benchmark = next(
        signal
        for signal in manifest["signals"]
        if signal["source_name"] == benchmark_source
    )
    benchmark_process = str(benchmark["template_name"])

    products: list[dict[str, str | bool]] = []
    for region in REGIONS:
        for category in ("pass", "fail"):
            selected = [
                row
                for row in rows
                if row["region"] == region and row["top_category"] == category
            ]
            bins = sorted(
                {
                    (
                        float(row["recoil_low_gev"]),
                        float(row["recoil_high_gev"]),
                    )
                    for row in selected
                }
            )
            if not bins:
                continue
            edges = np.asarray(
                [low for low, _high in bins] + [bins[-1][1]],
                dtype=float,
            )

            def values_for(process: str, field: str = "yield") -> np.ndarray:
                lookup = {
                    (
                        float(row["recoil_low_gev"]),
                        float(row["recoil_high_gev"]),
                    ): float(row[field])
                    for row in selected
                    if row["process"] == process
                }
                return np.asarray([lookup.get(bin_edges, 0.0) for bin_edges in bins])

            background_values = [values_for(process) for process in BACKGROUNDS]
            total_background = np.sum(background_values, axis=0)
            total_variance = np.sum(
                [values_for(process, "mc_variance") for process in BACKGROUNDS],
                axis=0,
            )
            total_uncertainty = np.sqrt(np.clip(total_variance, 0.0, None))

            figure, (axis, ratio_axis) = plt.subplots(
                2,
                1,
                figsize=(11.0, 11.0),
                sharex=True,
                gridspec_kw={"height_ratios": [3.2, 1.0], "hspace": 0.05},
            )
            hep.histplot(
                background_values,
                bins=edges,
                stack=True,
                histtype="fill",
                label=[BACKGROUND_LABELS[process] for process in BACKGROUNDS],
                color=[BACKGROUND_COLORS[process] for process in BACKGROUNDS],
                edgecolor="black",
                linewidth=0.35,
                ax=axis,
            )

            lower = np.clip(total_background - total_uncertainty, 1e-6, None)
            upper = total_background + total_uncertainty
            axis.fill_between(
                edges,
                np.r_[lower, lower[-1]],
                np.r_[upper, upper[-1]],
                step="post",
                facecolor="none",
                edgecolor="black",
                hatch="////",
                linewidth=0.0,
                label="MC statistical uncertainty",
            )

            is_blinded = region == "sr"
            data_available = bool(data_availability.get(region, False))
            if region == "sr":
                benchmark_values = values_for(benchmark_process)
                hep.histplot(
                    benchmark_values,
                    bins=edges,
                    histtype="step",
                    color="#7b3294",
                    linewidth=2.2,
                    label=(
                        rf"Signal $m_V={benchmark['mphi']}$ GeV, "
                        rf"$m_\chi={benchmark['mchi']}$ GeV"
                    ),
                    ax=axis,
                )
            if not data_available:
                axis.plot(
                    [],
                    [],
                    linestyle="none",
                    marker="",
                    label="Data unavailable",
                )
            elif is_blinded:
                axis.plot(
                    [],
                    [],
                    linestyle="none",
                    marker="",
                    label="SR data blinded",
                )
            else:
                data = values_for("data_obs")
                hep.histplot(
                    data,
                    bins=edges,
                    yerr=np.sqrt(np.clip(data, 0.0, None)),
                    histtype="errorbar",
                    color="black",
                    marker="o",
                    markersize=6,
                    capsize=2,
                    label="Data",
                    ax=axis,
                )

            valid_mc = total_background > 0.0
            relative_uncertainty = np.divide(
                total_uncertainty,
                total_background,
                out=np.zeros_like(total_uncertainty),
                where=valid_mc,
            )
            ratio_lower = 1.0 - relative_uncertainty
            ratio_upper = 1.0 + relative_uncertainty
            ratio_axis.fill_between(
                edges,
                np.r_[ratio_lower, ratio_lower[-1]],
                np.r_[ratio_upper, ratio_upper[-1]],
                step="post",
                facecolor="0.75",
                edgecolor="0.35",
                linewidth=0.8,
                alpha=0.65,
            )
            ratio_axis.axhline(1.0, color="black", linewidth=1.0)
            if not data_available:
                ratio_axis.text(
                    0.5,
                    0.5,
                    "Data unavailable",
                    transform=ratio_axis.transAxes,
                    ha="center",
                    va="center",
                    fontsize=14,
                )
            elif is_blinded:
                ratio_axis.text(
                    0.5,
                    0.5,
                    "Blinded",
                    transform=ratio_axis.transAxes,
                    ha="center",
                    va="center",
                    fontsize=14,
                )
            else:
                data_ratio = np.divide(
                    data,
                    total_background,
                    out=np.full_like(data, np.nan),
                    where=valid_mc,
                )
                data_ratio_uncertainty = np.divide(
                    np.sqrt(np.clip(data, 0.0, None)),
                    total_background,
                    out=np.full_like(data, np.nan),
                    where=valid_mc,
                )
                hep.histplot(
                    data_ratio,
                    bins=edges,
                    yerr=data_ratio_uncertainty,
                    histtype="errorbar",
                    color="black",
                    marker="o",
                    markersize=5,
                    capsize=2,
                    ax=ratio_axis,
                )

            positive = total_background[total_background > 0.0]
            ymin = max(float(np.min(positive)) * 0.08, 0.01) if len(positive) else 0.01
            ymax = max(float(np.max(upper)) * 60.0, ymin * 100.0)
            axis.set_yscale("log")
            axis.set_ylim(ymin, ymax)
            axis.set_xlim(edges[0], edges[-1])
            axis.set_ylabel("Events")
            axis.grid(alpha=0.15, which="both", axis="y")
            axis.legend(ncol=2, fontsize=9.5, loc="upper right")
            ratio_axis.set_ylim(0.5, 1.5)
            ratio_axis.set_ylabel("Data / MC")
            ratio_axis.set_xlabel(r"$U_T$ [GeV]")
            ratio_axis.grid(alpha=0.18, axis="y")
            cms_label(axis, luminosity_fb)
            figure.subplots_adjust(
                left=0.14,
                right=0.97,
                bottom=0.11,
                top=0.88,
                hspace=0.05,
            )

            base_path = plot_dir / f"{region}_{category}"
            save_png_pdf(figure, base_path)
            plt.close(figure)
            products.append(
                {
                    "region": region,
                    "top_category": category,
                    "data_blinded": is_blinded,
                    "data_available": data_available,
                    "png": str(base_path.with_suffix(".png").relative_to(output)),
                    "pdf": str(base_path.with_suffix(".pdf").relative_to(output)),
                }
            )

    write_json(plot_dir / "manifest.json", products)
    print(f"Wrote {len(products)} separate SR/CR yield plots to {plot_dir}")


if __name__ == "__main__":
    main()
