#!/usr/bin/env python3
"""Build pass/fail transfer factors, ROOT templates, and Combine datacards."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

import cloudpickle
import hist
import lz4.frame
import numpy as np
import uproot

from common import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT,
    ensure_directories,
    load_config,
    signal_metadata,
    write_json,
)


BACKGROUND_SOURCES = OrderedDict(
    [
        ("top", ["TT", "ST"]),
        ("wjets", ["W ($\\ell\\nu$) + Jets"]),
        ("zjets", ["Z ($\\nu\\nu$) + Jets"]),
        ("zll", ["Z ($\\ell\\ell$) + Jets"]),
        ("gjets", ["G + Jets"]),
        ("diboson", ["WW", "WZ", "ZZ"]),
        ("qcd", ["QCD Multijet"]),
    ]
)
PROCESSES = ["signal", *BACKGROUND_SOURCES]
PROCESS_IDS = {"signal": 0, **{name: i + 1 for i, name in enumerate(BACKGROUND_SOURCES)}}
TF_DEFINITIONS = [
    ("z", "gcr", "zjets", "gjets"),
    ("z", "zmcr", "zjets", "zll"),
    ("z", "zecr", "zjets", "zll"),
    ("w", "wmcr", "wjets", "wjets"),
    ("w", "wecr", "wjets", "wjets"),
    ("top", "tmcr", "top", "top"),
    ("top", "tecr", "top", "top"),
]


def load_accumulator(path: Path) -> dict[str, Any]:
    with lz4.frame.open(path) as handle:
        return cloudpickle.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input", type=Path, help="Override the input .scaled file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def channel_name(region: str, category: str, recoil_bin: int) -> str:
    tag = "p" if category == "pass" else "f"
    return f"{region}_{tag}_b{recoil_bin}"


def region_available(histogram: Any, region: str) -> bool:
    return region in list(histogram.axes["region"])


def rebinned_yield(
    histogram: Any,
    region: str,
    category_index: int,
    low: float,
    high: float,
    *,
    fold_overflow: bool,
    final_bin: bool,
) -> tuple[float, float]:
    if not region_available(histogram, region):
        return 0.0, 0.0
    selected = histogram[{"region": region}]
    values = np.asarray(selected.values(), dtype=float)
    variances_raw = selected.variances()
    variances = (
        np.asarray(variances_raw, dtype=float)
        if variances_raw is not None
        else np.maximum(values, 0.0)
    )
    source_edges = np.asarray(selected.axes[0].edges, dtype=float)
    source_low = source_edges[:-1]
    source_high = source_edges[1:]
    if fold_overflow and final_bin:
        mask = source_low >= low - 1e-9
    else:
        mask = (source_low >= low - 1e-9) & (source_high <= high + 1e-9)
    value = float(np.sum(values[mask, category_index]))
    variance = float(np.sum(variances[mask, category_index]))
    if fold_overflow and final_bin and selected.axes[0].traits.overflow:
        flow_values = np.asarray(selected.values(flow=True), dtype=float)
        flow_variances_raw = selected.variances(flow=True)
        flow_variances = (
            np.asarray(flow_variances_raw, dtype=float)
            if flow_variances_raw is not None
            else np.maximum(flow_values, 0.0)
        )
        value += float(flow_values[-1, category_index])
        variance += float(flow_variances[-1, category_index])
    return value, max(variance, 0.0)


def grouped_yield(
    source: dict[str, Any],
    source_names: list[str],
    region: str,
    category_index: int,
    low: float,
    high: float,
    *,
    fold_overflow: bool,
    final_bin: bool,
) -> tuple[float, float]:
    total = 0.0
    variance = 0.0
    for source_name in source_names:
        value, var = rebinned_yield(
            source[source_name],
            region,
            category_index,
            low,
            high,
            fold_overflow=fold_overflow,
            final_bin=final_bin,
        )
        total += value
        variance += var
    return total, variance


def make_weight_histogram(value: float, variance: float) -> hist.Hist:
    output = hist.Hist(
        hist.axis.Regular(1, 0.0, 1.0, name="count"),
        storage=hist.storage.Weight(),
    )
    view = output.view()
    view.value[...] = max(value, 1e-6)
    view.variance[...] = max(variance, 1e-12)
    return output


def nuisance_line(
    name: str,
    kind: str,
    columns: list[tuple[str, str]],
    selector: Any,
) -> str:
    entries = [selector(channel, process) for channel, process in columns]
    return f"{name:<34} {kind:<6} " + " ".join(entries)


def build_datacard(
    *,
    path: Path,
    signal: dict[str, Any],
    channels: list[str],
    config: dict[str, Any],
) -> None:
    era = str(config["era"])
    nuisance_era = re.sub(r"[^A-Za-z0-9_]", "_", era)
    lumi_nuisance_name = f"lumi_{nuisance_era}"
    columns = [(channel, process) for channel in channels for process in PROCESSES]
    template_relpath = "../templates/templates.root"
    lines = [
        f"imax {len(channels)}",
        f"jmax {len(BACKGROUND_SOURCES)}",
        "kmax *",
        "------------",
        (
            f"shapes signal * {template_relpath} "
            f"$CHANNEL/{signal['template_name']}"
        ),
        (
            f"shapes * * {template_relpath} "
            "$CHANNEL/$PROCESS $CHANNEL/$PROCESS_$SYSTEMATIC"
        ),
        "------------",
        "bin " + " ".join(channels),
        "observation " + " ".join(["-1"] * len(channels)),
        "------------",
        "bin " + " ".join(channel for channel, _ in columns),
        "process " + " ".join(process for _, process in columns),
        "process " + " ".join(str(PROCESS_IDS[process]) for _, process in columns),
        "rate " + " ".join(["-1"] * len(columns)),
        "------------",
    ]

    nuisances = config["nuisances"]
    lines.append(
        nuisance_line(
            lumi_nuisance_name,
            "lnN",
            columns,
            lambda _c, p: (
                f"{nuisances[lumi_nuisance_name]:.3f}"
                if p in {"signal", "diboson", "qcd"}
                else "-"
            ),
        )
    )
    lines.append(
        nuisance_line(
            "signal_norm",
            "lnN",
            columns,
            lambda _c, p: f"{nuisances['signal_norm']:.3f}" if p == "signal" else "-",
        )
    )
    lines.append(
        nuisance_line(
            "diboson_norm",
            "lnN",
            columns,
            lambda _c, p: (
                f"{nuisances['diboson_norm']:.3f}" if p == "diboson" else "-"
            ),
        )
    )
    lines.append(
        nuisance_line(
            "qcd_norm",
            "lnN",
            columns,
            lambda _c, p: f"{nuisances['qcd_norm']:.3f}" if p == "qcd" else "-",
        )
    )

    tf_nuisance_names: list[str] = []
    recoil_edges = config["recoil_edges_gev"]
    for category in config["top_categories"]:
        tag = "p" if category == "pass" else "f"
        for recoil_bin in range(len(recoil_edges) - 1):
            sr_channel = channel_name("sr", category, recoil_bin)
            for family, process in [("z", "zjets"), ("w", "wjets"), ("top", "top")]:
                nuisance_name = f"tf_{family}_{tag}_b{recoil_bin}"
                tf_nuisance_names.append(nuisance_name)
                value = nuisances[f"tf_{family}"]
                lines.append(
                    nuisance_line(
                        nuisance_name,
                        "lnN",
                        columns,
                        lambda c, p, target_c=sr_channel, target_p=process, v=value: (
                            f"{v:.3f}" if c == target_c and p == target_p else "-"
                        ),
                    )
                )

    lines.append("------------")
    for category in config["top_categories"]:
        tag = "p" if category == "pass" else "f"
        for recoil_bin in range(len(recoil_edges) - 1):
            relevant_channels = [
                channel_name(region, category, recoil_bin)
                for region in config["regions"]
            ]
            parameter_targets = {
                f"z_norm_{tag}_b{recoil_bin}": ["zjets", "zll", "gjets"],
                f"w_norm_{tag}_b{recoil_bin}": ["wjets"],
                f"top_norm_{tag}_b{recoil_bin}": ["top"],
            }
            for parameter, processes in parameter_targets.items():
                for channel in relevant_channels:
                    for process in processes:
                        lines.append(
                            f"{parameter:<34} rateParam {channel} {process} 1.0 [0,5]"
                        )

    threshold = int(config["auto_mc_stats_threshold"])
    lines.extend(
        [
            f"* autoMCStats {threshold}",
            (
                f"normalization group = {lumi_nuisance_name} "
                "signal_norm diboson_norm qcd_norm"
            ),
            "transfer group = " + " ".join(tf_nuisance_names),
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.input is not None:
        input_path = args.input.expanduser().resolve()
    else:
        configured_input = Path(config["input"]).expanduser()
        input_path = (
            configured_input.resolve()
            if configured_input.is_absolute()
            else (args.config.expanduser().resolve().parent / configured_input).resolve()
        )
    if not input_path.is_file():
        raise SystemExit(f"Input file does not exist: {input_path}")
    output = args.output.resolve()
    template_dir = output / "templates"
    datacard_dir = output / "datacards"
    validation_dir = output / "validation"
    ensure_directories([template_dir, datacard_dir, validation_dir])

    accumulator = load_accumulator(input_path)
    histogram_name = config["histogram"]
    background_histograms = accumulator["bkg"][histogram_name]
    signal_histograms = accumulator["sig"][histogram_name]
    data_histograms = accumulator["data"][histogram_name]
    data_availability_by_region = {
        region: config["data_streams"][region] in data_histograms
        for region in config["regions"]
    }
    signals = sorted(
        (signal_metadata(name) for name in signal_histograms),
        key=lambda item: (item["mphi"], item["mchi"]),
    )

    edges = [float(value) for value in config["recoil_edges_gev"]]
    fold_overflow = bool(config["fold_recoil_overflow"])
    yields: dict[str, dict[str, tuple[float, float]]] = {}
    validation_rows: list[dict[str, Any]] = []
    channels: list[str] = []

    for category, category_index in config["top_categories"].items():
        for recoil_bin, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
            final_bin = recoil_bin == len(edges) - 2
            for region in config["regions"]:
                channel = channel_name(region, category, recoil_bin)
                channels.append(channel)
                channel_yields: dict[str, tuple[float, float]] = {}
                for process, sources in BACKGROUND_SOURCES.items():
                    channel_yields[process] = grouped_yield(
                        background_histograms,
                        sources,
                        region,
                        category_index,
                        low,
                        high,
                        fold_overflow=fold_overflow,
                        final_bin=final_bin,
                    )
                data_stream = config["data_streams"][region]
                if data_availability_by_region[region]:
                    channel_yields["data_obs"] = rebinned_yield(
                        data_histograms[data_stream],
                        region,
                        category_index,
                        low,
                        high,
                        fold_overflow=fold_overflow,
                        final_bin=final_bin,
                    )
                else:
                    asimov_yield = sum(
                        channel_yields[process][0] for process in BACKGROUND_SOURCES
                    )
                    channel_yields["data_obs"] = (max(asimov_yield, 0.0), 0.0)
                yields[channel] = channel_yields
                for process, (value, variance) in channel_yields.items():
                    validation_rows.append(
                        {
                            "channel": channel,
                            "region": region,
                            "top_category": category,
                            "recoil_low_gev": low,
                            "recoil_high_gev": high,
                            "process": process,
                            "yield": value,
                            "mc_variance": variance,
                        }
                    )

    signal_yields: dict[str, dict[str, tuple[float, float]]] = {}
    for signal in signals:
        source_name = str(signal["source_name"])
        signal_yields[source_name] = {}
        source_histogram = signal_histograms[source_name]
        for category, category_index in config["top_categories"].items():
            for recoil_bin, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
                final_bin = recoil_bin == len(edges) - 2
                for region in config["regions"]:
                    channel = channel_name(region, category, recoil_bin)
                    value_variance = rebinned_yield(
                        source_histogram,
                        region,
                        category_index,
                        low,
                        high,
                        fold_overflow=fold_overflow,
                        final_bin=final_bin,
                    )
                    signal_yields[source_name][channel] = value_variance
                    validation_rows.append(
                        {
                            "channel": channel,
                            "region": region,
                            "top_category": category,
                            "recoil_low_gev": low,
                            "recoil_high_gev": high,
                            "process": signal["template_name"],
                            "yield": value_variance[0],
                            "mc_variance": value_variance[1],
                        }
                    )

    template_path = template_dir / "templates.root"
    clipped: list[dict[str, Any]] = []
    with uproot.recreate(template_path) as root_file:
        for channel in channels:
            data_value = max(0.0, yields[channel]["data_obs"][0])
            root_file[f"{channel}/data_obs"] = (
                np.asarray([data_value], dtype=np.float64),
                np.asarray([0.0, 1.0], dtype=np.float64),
            )
            for process in BACKGROUND_SOURCES:
                value, variance = yields[channel][process]
                if value <= 0.0:
                    clipped.append(
                        {"channel": channel, "process": process, "original": value}
                    )
                root_file[f"{channel}/{process}"] = make_weight_histogram(value, variance)
            for signal in signals:
                value, variance = signal_yields[str(signal["source_name"])][channel]
                if value <= 0.0:
                    clipped.append(
                        {
                            "channel": channel,
                            "process": signal["template_name"],
                            "original": value,
                        }
                    )
                root_file[
                    f"{channel}/{signal['template_name']}"
                ] = make_weight_histogram(value, variance)

    transfer_rows: list[dict[str, Any]] = []
    for category in config["top_categories"]:
        for recoil_bin, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
            sr_channel = channel_name("sr", category, recoil_bin)
            for family, control_region, numerator_process, denominator_process in TF_DEFINITIONS:
                control_channel = channel_name(control_region, category, recoil_bin)
                numerator, numerator_var = yields[sr_channel][numerator_process]
                denominator, denominator_var = yields[control_channel][denominator_process]
                if numerator > 0.0 and denominator > 0.0:
                    transfer_factor = numerator / denominator
                    relative_var = numerator_var / numerator**2 + denominator_var / denominator**2
                    mcstat = transfer_factor * math.sqrt(max(relative_var, 0.0))
                else:
                    transfer_factor = None
                    mcstat = None
                transfer_rows.append(
                    {
                        "family": family,
                        "top_category": category,
                        "recoil_bin": recoil_bin,
                        "recoil_low_gev": low,
                        "recoil_high_gev": high,
                        "signal_region": "sr",
                        "control_region": control_region,
                        "numerator_process": numerator_process,
                        "denominator_process": denominator_process,
                        "numerator_yield": numerator,
                        "denominator_yield": denominator,
                        "transfer_factor": transfer_factor,
                        "mcstat_uncertainty": mcstat,
                        "assigned_relative_systematic": (
                            float(config["nuisances"][f"tf_{family}"]) - 1.0
                        ),
                    }
                )

    transfer_json = output / "transfer_factors.json"
    transfer_csv = output / "transfer_factors.csv"
    write_json(transfer_json, transfer_rows)
    with transfer_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(transfer_rows[0]))
        writer.writeheader()
        writer.writerows(transfer_rows)

    validation_csv = validation_dir / "yields.csv"
    with validation_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(validation_rows[0]))
        writer.writeheader()
        writer.writerows(validation_rows)
    write_json(validation_dir / "clipped_bins.json", clipped)

    total_background_sr = sum(
        value
        for channel, process_yields in yields.items()
        if channel.startswith("sr_")
        for process, (value, _variance) in process_yields.items()
        if process in BACKGROUND_SOURCES
    )
    manifest_signals: list[dict[str, Any]] = []
    expected_card_names: set[str] = set()
    for signal in signals:
        source_name = str(signal["source_name"])
        card_name = f"datacard_{signal['label']}.txt"
        expected_card_names.add(card_name)
        card_path = datacard_dir / card_name
        build_datacard(
            path=card_path,
            signal=signal,
            channels=channels,
            config=config,
        )
        sr_signal = sum(
            value
            for channel, (value, _variance) in signal_yields[source_name].items()
            if channel.startswith("sr_")
        )
        approximate_rmax = (
            max(10.0, 50.0 * math.sqrt(max(total_background_sr, 1.0)) / sr_signal)
            if sr_signal > 0.0
            else 1.0e7
        )
        manifest_signals.append(
            {
                **signal,
                "datacard": str(card_path.relative_to(output)),
                "sr_signal_yield": sr_signal,
                "recommended_rmax": min(1.0e7, approximate_rmax),
            }
        )

    for stale_card in datacard_dir.glob("datacard_*.txt"):
        if stale_card.name not in expected_card_names:
            stale_card.unlink()

    manifest = {
        "analysis": config["analysis"],
        "era": config["era"],
        "luminosity_fb": float(config["luminosity_fb"]),
        "input": str(input_path),
        "input_sha256": file_sha256(input_path),
        "histogram": histogram_name,
        "recoil_edges_gev": edges,
        "fold_recoil_overflow": fold_overflow,
        "channels": channels,
        "processes": PROCESSES,
        "template": str(template_path.relative_to(output)),
        "transfer_factors": str(transfer_json.relative_to(output)),
        "benchmark_signal": config["benchmark_signal"],
        "data_available_by_region": data_availability_by_region,
        "observation_mode_by_region": {
            region: (
                "recorded_data"
                if data_availability_by_region[region]
                else "background_asimov"
            )
            for region in config["regions"]
        },
        "signals": manifest_signals,
        "model_scope": (
            f"Nominal {config['era']} model with pass/fail categories, per-bin control-region "
            "rate parameters, MC statistical uncertainties, and assigned normalization/"
            "transfer-factor nuisances. Input contains no shape-systematic variations."
        ),
    }
    write_json(output / "manifest.json", manifest)

    print(f"Built {len(channels)} channels and {len(signals)} signal datacards")
    print(f"Templates: {template_path}")
    print(f"Transfer factors: {transfer_csv}")
    print(f"Manifest: {output / 'manifest.json'}")


if __name__ == "__main__":
    main()
