#!/usr/bin/env python3
"""Validate the generated templates, limits, interpolation, and impacts."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import uproot

from common import DEFAULT_OUTPUT, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    limits = json.loads((output / "limits" / "limits.json").read_text())
    benchmark = next(
        signal
        for signal in manifest["signals"]
        if signal["source_name"] == manifest["benchmark_signal"]
    )
    impacts = json.loads(
        (
            output
            / "impacts"
            / f"impacts_{benchmark['label']}.json"
        ).read_text()
    )
    transfer_plots = json.loads(
        (output / "plots" / "transfer_factors" / "manifest.json").read_text()
    )
    region_plots = json.loads(
        (output / "plots" / "regions" / "manifest.json").read_text()
    )
    clipped = json.loads((output / "validation" / "clipped_bins.json").read_text())
    issues: list[str] = []

    datacards = [output / signal["datacard"] for signal in manifest["signals"]]
    for datacard in datacards:
        auto_mc_stats_lines = [
            line.strip()
            for line in datacard.read_text().splitlines()
            if "autoMCStats" in line
        ]
        if auto_mc_stats_lines != ["* autoMCStats 10"]:
            issues.append(
                f"{datacard.name}: expected exactly '* autoMCStats 10', "
                f"found {auto_mc_stats_lines}"
            )

    if len(limits) != len(manifest["signals"]):
        issues.append(
            f"Found {len(limits)} limits for {len(manifest['signals'])} signal points"
        )
    for row in limits:
        expected = [
            row["expected_minus2"],
            row["expected_minus1"],
            row["expected"],
            row["expected_plus1"],
            row["expected_plus2"],
        ]
        if any(not math.isfinite(value) or value <= 0.0 for value in expected):
            issues.append(f"{row['label']}: non-positive/non-finite expected limit")
        if expected != sorted(expected):
            issues.append(f"{row['label']}: expected quantiles are not monotonic")
        if "observed" in row:
            issues.append(f"{row['label']}: observed result present in blinded output")
        if max(expected) >= 0.9 * row["rmax"]:
            issues.append(f"{row['label']}: result is too close to rMax")

    template_path = output / manifest["template"]
    with uproot.open(template_path) as root_file:
        template_keys = root_file.keys(recursive=True)
        expected_key_count = len(manifest["channels"]) * (
            1 + 7 + len(manifest["signals"])
        )
        histogram_count = sum(";" in key and not key.rstrip(";1").endswith("/") for key in template_keys)
        if histogram_count < expected_key_count:
            issues.append(
                f"Template has {histogram_count} histograms; expected at least {expected_key_count}"
            )

    surface_data = np.load(output / "interpolation" / "limit_surfaces.npz")
    interpolation_summary = json.loads(
        (output / "interpolation" / "interpolation_summary.json").read_text()
    )
    on_shell_interpolation_summary = json.loads(
        (
            output
            / "interpolation_on_shell_only"
            / "interpolation_summary.json"
        ).read_text()
    )
    relic_summaries = [
        interpolation_summary.get("relic_density", {}),
        on_shell_interpolation_summary.get("relic_density", {}),
    ]
    for subdirectory, relic_summary in zip(
        ("interpolation", "interpolation_on_shell_only"),
        relic_summaries,
    ):
        if relic_summary.get("constraint") != 0.12:
            issues.append(f"{subdirectory}: missing Omega_chi*h^2=0.12 contour")
        if int(relic_summary.get("n_contour_segments", 0)) < 1:
            issues.append(f"{subdirectory}: relic-density contour has no segments")
        if not (output / subdirectory / "limit_interpolation.png").is_file():
            issues.append(f"{subdirectory}: missing 2D limit PNG")
        if not (output / subdirectory / "limit_interpolation.pdf").is_file():
            issues.append(f"{subdirectory}: missing 2D limit PDF")
    if relic_summaries[0].get("sha256") != relic_summaries[1].get("sha256"):
        issues.append("Full and on-shell plots use different relic-density inputs")
    finite_surface_bins = int(np.isfinite(surface_data["expected"]).sum())
    if finite_surface_bins == 0:
        issues.append("Interpolated expected surface has no finite bins")
    if len(transfer_plots) != 8:
        issues.append(f"Found {len(transfer_plots)} TF plots; expected 8")
    if len(region_plots) != 16:
        issues.append(f"Found {len(region_plots)} SR/CR plots; expected 16")
    for product in [*transfer_plots, *region_plots]:
        for extension in ("png", "pdf"):
            if not (output / str(product[extension])).is_file():
                issues.append(f"Missing plot product: {product[extension]}")

    on_shell_surface_data = np.load(
        output / "interpolation_on_shell_only" / "limit_surfaces.npz"
    )
    finite_on_shell_bins = int(np.isfinite(on_shell_surface_data["expected"]).sum())
    if finite_on_shell_bins == 0:
        issues.append("On-shell interpolated expected surface has no finite bins")
    brazil_metadata = json.loads(
        (
            output
            / "interpolation_on_shell_only"
            / "limit_brazil_mx200.json"
        ).read_text()
    )
    if brazil_metadata.get("shell_mode") != "on-shell-only":
        issues.append("mX=200 Brazilian plot is not on-shell-only")
    if brazil_metadata.get("observed_limit_drawn") is not False:
        issues.append("mX=200 Brazilian plot is not blinded")
    if brazil_metadata.get("displayed_mV_range_gev") != [500.0, 2000.0]:
        issues.append("mX=200 Brazilian plot does not use mV range 500--2000 GeV")

    clipped_counts = Counter(
        "signal" if str(item["process"]).startswith("signal_") else item["process"]
        for item in clipped
    )
    negative_background_bins = [
        item
        for item in clipped
        if item["original"] < 0.0 and not str(item["process"]).startswith("signal_")
    ]
    result: dict[str, Any] = {
        "status": "ok" if not issues else "failed",
        "issues": issues,
        "counts": {
            "channels": len(manifest["channels"]),
            "signal_points": len(manifest["signals"]),
            "datacards_with_background_only_auto_mc_stats": len(datacards),
            "limit_points": len(limits),
            "limit_root_files": len(list((output / "limits" / "raw").glob("*.root"))),
            "transfer_factor_rows": len(
                json.loads((output / "transfer_factors.json").read_text())
            ),
            "transfer_factor_plots": len(transfer_plots),
            "region_yield_plots": len(region_plots),
            "impact_parameters": len(impacts["params"]),
            "finite_interpolation_bins": finite_surface_bins,
            "finite_on_shell_interpolation_bins": finite_on_shell_bins,
            "relic_density_contours": sum(
                int(summary.get("n_contour_segments", 0))
                for summary in relic_summaries
            ),
        },
        "clipping": {
            "counts_by_family": dict(clipped_counts),
            "negative_background_bins": negative_background_bins,
            "policy": (
                "Non-positive nominal process bins are replaced by 1e-6 events in the "
                "Combine template and retained in clipped_bins.json for auditability."
            ),
        },
        "input_sha256": manifest["input_sha256"],
        "relic_density_sha256": relic_summaries[0].get("sha256"),
        "model_scope": manifest["model_scope"],
    }
    write_json(output / "validation" / "validation_report.json", result)
    if issues:
        raise SystemExit("\n".join(issues))
    print(json.dumps(result["counts"], indent=2))
    print(f"Validation status: {result['status']}")


if __name__ == "__main__":
    main()
