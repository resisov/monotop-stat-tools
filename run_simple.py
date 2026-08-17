#!/usr/bin/env python3
"""One-command pass/fail, transfer-factor, blinded-limit, and impact workflow.

Example
-------
python3 run_simple.py \
  --input /path/to/hadmonotop2023.scaled \
  --era 2023 \
  --lumi 17.96 \
  --combine-prefix /path/to/conda/env \
  --output outputs/2023
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = REPO_ROOT / "workflow"
STAGES = ("build", "plots", "limits", "interpolation", "impacts", "validate")
COMBINE_TOOLS = ("combine", "text2workspace.py", "combineTool.py", "plotImpacts.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build pass/fail templates, plot all regions and transfer factors, "
            "calculate blinded expected limits, and run blinded impacts."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Analysis JSON; command-line values override matching fields",
    )
    parser.add_argument("--input", type=Path, help="Input .scaled file")
    parser.add_argument("--era", help="Era label, for example 2023")
    parser.add_argument("--lumi", type=float, help="Luminosity in fb^-1")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory; defaults to outputs/<era>",
    )
    parser.add_argument(
        "--combine-prefix",
        type=Path,
        help="Environment prefix containing the CMS Combine command suite",
    )
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument(
        "--benchmark",
        default=None,
        help="Representative signal drawn in SR plots",
    )
    parser.add_argument(
        "--shell-mode",
        choices=("all", "on-shell-only"),
        default="all",
        help="Mass points used in the two-dimensional limit interpolation",
    )
    parser.add_argument(
        "--lumi-uncertainty",
        type=float,
        default=None,
        help="Multiplicative luminosity lnN nuisance",
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=STAGES,
        default=list(STAGES),
        help="Stages to run in canonical order; omitted dependencies must already exist",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recalculate the selected workflow products",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write nothing and only print the commands that would run",
    )
    return parser.parse_args()


def command_text(command: list[str]) -> str:
    return " ".join(shlex_quote(part) for part in command)


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def run(command: list[str], *, dry_run: bool) -> None:
    print(f"+ {command_text(command)}", flush=True)
    if not dry_run:
        subprocess.run(command, cwd=REPO_ROOT, check=True)


def check_benchmark(output: Path, requested: str) -> str:
    manifest = json.loads((output / "manifest.json").read_text())
    matching = [
        signal for signal in manifest["signals"] if signal["source_name"] == requested
    ]
    if len(matching) != 1:
        available = {signal["source_name"] for signal in manifest["signals"]}
        examples = ", ".join(sorted(available)[:5])
        raise SystemExit(
            f"Benchmark signal {requested!r} is not present in the input. "
            f"Choose one with --benchmark. Examples: {examples}"
        )
    return str(matching[0]["label"])


def resolve_combine_prefix(requested: Path | None) -> Path | None:
    candidates: list[Path] = []
    if requested is not None:
        candidates.append(requested.expanduser())
    for variable in ("COMBINE_PREFIX", "CONDA_PREFIX"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]))

    for candidate in candidates:
        prefix = candidate.resolve()
        if all((prefix / "bin" / executable).is_file() for executable in COMBINE_TOOLS):
            return prefix

    if requested is not None:
        raise SystemExit(
            f"Invalid --combine-prefix: {requested}. Expected these executables "
            f"below bin/: {', '.join(COMBINE_TOOLS)}."
        )
    if all(shutil.which(executable) for executable in COMBINE_TOOLS):
        return None
    raise SystemExit(
        "CMS Combine was not found. Activate the Combine environment or pass "
        "--combine-prefix /path/to/environment."
    )


def default_analysis_config(
    *,
    era: str,
    luminosity_fb: float,
    input_path: Path,
    benchmark: str,
    luminosity_uncertainty: float,
) -> dict[str, object]:
    nuisance_era = re.sub(r"[^A-Za-z0-9_]", "_", era)
    return {
        "analysis": "hadronic_monotop",
        "era": era,
        "luminosity_fb": float(luminosity_fb),
        "input": str(input_path),
        "histogram": "ut_bin",
        "recoil_edges_gev": [350.0, 400.0, 500.0, 600.0, 700.0, 1000.0],
        "fold_recoil_overflow": True,
        "top_categories": {"fail": 0, "pass": 1},
        "regions": ["sr", "wmcr", "wecr", "tmcr", "tecr", "gcr", "zmcr", "zecr"],
        "data_streams": {
            "sr": "MET",
            "wmcr": "MET",
            "wecr": "EGamma",
            "tmcr": "MET",
            "tecr": "EGamma",
            "gcr": "EGamma",
            "zmcr": "MET",
            "zecr": "EGamma",
        },
        "benchmark_signal": benchmark,
        "nuisances": {
            f"lumi_{nuisance_era}": float(luminosity_uncertainty),
            "signal_norm": 1.10,
            "diboson_norm": 1.20,
            "qcd_norm": 1.50,
            "tf_z": 1.10,
            "tf_w": 1.10,
            "tf_top": 1.15,
        },
        "auto_mc_stats_threshold": 10,
    }


def resolve_input_path(value: str | Path, *, base: Path) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def resolve_config(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if args.config is None:
        missing = [
            option
            for option, value in (
                ("--input", args.input),
                ("--era", args.era),
                ("--lumi", args.lumi),
            )
            if value is None
        ]
        if missing:
            raise SystemExit(
                "Required without --config: " + ", ".join(missing)
            )
        input_path = resolve_input_path(args.input, base=Path.cwd())
        benchmark = args.benchmark or "sig_Mphi-1000_Mchi-150"
        luminosity_uncertainty = (
            1.014 if args.lumi_uncertainty is None else args.lumi_uncertainty
        )
        return (
            default_analysis_config(
                era=str(args.era),
                luminosity_fb=float(args.lumi),
                input_path=input_path,
                benchmark=benchmark,
                luminosity_uncertainty=float(luminosity_uncertainty),
            ),
            input_path,
        )

    config_path = args.config.expanduser().resolve()
    if not config_path.is_file():
        raise SystemExit(f"Configuration file does not exist: {config_path}")
    try:
        config = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise SystemExit(f"Cannot read configuration {config_path}: {error}") from error
    if not isinstance(config, dict):
        raise SystemExit(f"Configuration must contain a JSON object: {config_path}")

    original_era = str(config.get("era", ""))
    input_value = args.input if args.input is not None else config.get("input")
    if input_value is None:
        raise SystemExit("Input is missing: set config.input or pass --input")
    input_base = Path.cwd() if args.input is not None else config_path.parent
    input_path = resolve_input_path(input_value, base=input_base)
    config["input"] = str(input_path)
    if args.era is not None:
        config["era"] = args.era
    if args.lumi is not None:
        config["luminosity_fb"] = float(args.lumi)
    if args.benchmark is not None:
        config["benchmark_signal"] = args.benchmark

    era = str(config.get("era", ""))
    nuisance_era = re.sub(r"[^A-Za-z0-9_]", "_", era)
    old_nuisance_era = re.sub(r"[^A-Za-z0-9_]", "_", original_era)
    nuisances = config.setdefault("nuisances", {})
    old_lumi_key = f"lumi_{old_nuisance_era}"
    lumi_key = f"lumi_{nuisance_era}"
    if lumi_key not in nuisances and old_lumi_key in nuisances:
        nuisances[lumi_key] = nuisances[old_lumi_key]
    if args.lumi_uncertainty is not None:
        nuisances[lumi_key] = float(args.lumi_uncertainty)
    return config, input_path


def validate_config_values(config: dict[str, Any], *, workers: int) -> None:
    required = {
        "analysis",
        "era",
        "luminosity_fb",
        "histogram",
        "recoil_edges_gev",
        "fold_recoil_overflow",
        "top_categories",
        "regions",
        "data_streams",
        "benchmark_signal",
        "nuisances",
        "auto_mc_stats_threshold",
    }
    missing = sorted(required - set(config))
    if missing:
        raise SystemExit("Missing configuration field(s): " + ", ".join(missing))
    if float(config["luminosity_fb"]) <= 0.0:
        raise SystemExit("--lumi must be positive")
    if workers < 1:
        raise SystemExit("--workers must be at least 1")
    if not str(config["era"]).strip():
        raise SystemExit("era must be a non-empty string")
    edges = [float(value) for value in config["recoil_edges_gev"]]
    if len(edges) < 2 or any(right <= left for left, right in zip(edges, edges[1:])):
        raise SystemExit("recoil_edges_gev must be strictly increasing")
    configured_regions = {str(region) for region in config["regions"]}
    missing_streams = sorted(configured_regions - set(config["data_streams"]))
    if missing_streams:
        raise SystemExit(
            "Missing data_streams entries for region(s): " + ", ".join(missing_streams)
        )
    nuisance_era = re.sub(r"[^A-Za-z0-9_]", "_", str(config["era"]))
    required_nuisances = {
        f"lumi_{nuisance_era}",
        "signal_norm",
        "diboson_norm",
        "qcd_norm",
        "tf_z",
        "tf_w",
        "tf_top",
    }
    missing_nuisances = sorted(required_nuisances - set(config["nuisances"]))
    if missing_nuisances:
        raise SystemExit(
            "Missing nuisance value(s): " + ", ".join(missing_nuisances)
        )
    luminosity_uncertainty = float(config["nuisances"][f"lumi_{nuisance_era}"])
    if luminosity_uncertainty < 1.0:
        raise SystemExit("The luminosity uncertainty must be multiplicative and >= 1")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_products_are_current(output: Path, input_path: Path) -> bool:
    manifest_path = output / "manifest.json"
    template_path = output / "templates" / "templates.root"
    if not manifest_path.is_file() or not template_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    cards = list((output / "datacards").glob("datacard_*.txt"))
    return (
        manifest.get("input_sha256") == file_sha256(input_path)
        and len(cards) == len(manifest.get("signals", []))
    )


def plot_products_are_complete(manifest_path: Path, output: Path, expected: int) -> bool:
    if not manifest_path.is_file():
        return False
    try:
        products = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return len(products) == expected and all(
        (output / str(product[extension])).is_file()
        for product in products
        for extension in ("png", "pdf")
    )


def limit_products_are_complete(output: Path) -> bool:
    manifest_path = output / "manifest.json"
    limits_path = output / "limits" / "limits.json"
    if not manifest_path.is_file() or not limits_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text())
        limits = json.loads(limits_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    expected_signals = {
        str(signal["source_name"]) for signal in manifest.get("signals", [])
    }
    returned_signals = {str(row.get("source_name")) for row in limits}
    return expected_signals == returned_signals and all(
        all(
            isinstance(row.get(field), (int, float)) and float(row[field]) > 0.0
            for field in (
                "expected_minus2",
                "expected_minus1",
                "expected",
                "expected_plus1",
                "expected_plus2",
            )
        )
        and (output / str(row.get("root_file", ""))).is_file()
        for row in limits
    )


def validate_products(
    output: Path,
    benchmark_label: str,
    *,
    auto_mc_stats_threshold: int,
    interpolation_subdirectory: str,
) -> dict[str, int | str]:
    manifest = json.loads((output / "manifest.json").read_text())
    limits = json.loads((output / "limits" / "limits.json").read_text())
    region_plots = json.loads(
        (output / "plots" / "regions" / "manifest.json").read_text()
    )
    tf_plots = json.loads(
        (output / "plots" / "transfer_factors" / "manifest.json").read_text()
    )
    impacts = json.loads(
        (output / "impacts" / f"impacts_{benchmark_label}.json").read_text()
    )
    cards = list((output / "datacards").glob("datacard_*.txt"))

    issues: list[str] = []
    if len(cards) != len(manifest["signals"]):
        issues.append(f"{len(cards)} datacards for {len(manifest['signals'])} signals")
    if len(limits) != len(manifest["signals"]):
        issues.append(f"{len(limits)} limits for {len(manifest['signals'])} signals")
    if any("observed" in row for row in limits):
        issues.append("observed result found in blinded limit table")
    quantile_fields = (
        "expected_minus2",
        "expected_minus1",
        "expected",
        "expected_plus1",
        "expected_plus2",
    )
    for row in limits:
        quantiles = [float(row[field]) for field in quantile_fields]
        if any(not math.isfinite(value) or value <= 0.0 for value in quantiles):
            issues.append(f"non-positive or non-finite limit for {row['label']}")
        if quantiles != sorted(quantiles):
            issues.append(f"non-monotonic expected quantiles for {row['label']}")
    if len(region_plots) != 16:
        issues.append(f"expected 16 region plots, found {len(region_plots)}")
    if len(tf_plots) != 8:
        issues.append(f"expected 8 transfer-factor plots, found {len(tf_plots)}")
    for card in cards:
        auto_mc_stats = [
            line.strip() for line in card.read_text().splitlines() if "autoMCStats" in line
        ]
        expected_line = f"* autoMCStats {auto_mc_stats_threshold}"
        if auto_mc_stats != [expected_line]:
            issues.append(f"unexpected autoMCStats configuration in {card.name}")
            break
    if not impacts.get("params"):
        issues.append("impact JSON has no nuisance parameters")
    for extension in ("png", "pdf"):
        limit_plot = (
            output
            / interpolation_subdirectory
            / f"limit_interpolation.{extension}"
        )
        if not limit_plot.is_file():
            issues.append(f"missing expected-limit plot: {limit_plot}")
    if issues:
        raise RuntimeError("Workflow validation failed: " + "; ".join(issues))

    return {
        "status": "ok",
        "channels": len(manifest["channels"]),
        "signal_points": len(manifest["signals"]),
        "region_plots": len(region_plots),
        "transfer_factor_plots": len(tf_plots),
        "blinded_limit_points": len(limits),
        "impact_parameters": len(impacts["params"]),
    }


def main() -> None:
    args = parse_args()
    config, input_path = resolve_config(args)
    validate_config_values(config, workers=args.workers)
    if not input_path.is_file():
        raise SystemExit(f"Input file does not exist: {input_path}")

    era = str(config["era"])
    luminosity_fb = float(config["luminosity_fb"])
    benchmark_source = str(config["benchmark_signal"])
    selected_stages = set(args.stages)
    output = (
        args.output.expanduser().resolve()
        if args.output
        else (REPO_ROOT / "outputs" / era).resolve()
    )
    needs_combine = bool(selected_stages & {"limits", "impacts"})
    combine_prefix = (
        args.combine_prefix.expanduser().resolve()
        if args.dry_run and args.combine_prefix is not None
        else resolve_combine_prefix(args.combine_prefix)
        if needs_combine and not args.dry_run
        else None
    )
    config_path = output / "analysis_config.json"
    resuming = False
    if (
        output.exists()
        and any(output.iterdir())
        and args.force
        and "build" not in selected_stages
    ):
        if not config_path.is_file():
            raise SystemExit(
                "Cannot force downstream stages in an unowned output directory. "
                "Include the build stage."
            )
        existing_config = json.loads(config_path.read_text())
        if existing_config != config:
            raise SystemExit(
                "The requested configuration differs from this output directory. "
                "Include the build stage when using --force."
            )
    if output.exists() and any(output.iterdir()) and not args.force:
        if not config_path.is_file():
            raise SystemExit(
                f"Output directory is not empty and has no workflow config: {output}\n"
                "Choose a new --output directory or add --force."
            )
        existing_config = json.loads(config_path.read_text())
        if existing_config != config:
            raise SystemExit(
                f"Output directory belongs to a different configuration: {output}\n"
                "Choose a new --output directory or add --force."
            )
        resuming = True
        print(f"Resuming matching output directory: {output}")
    if args.dry_run:
        print(f"Would write config: {config_path}")
        print(json.dumps(config, indent=2))
    else:
        output.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

    python = sys.executable
    build_command = [
        python,
        str(WORKFLOW_DIR / "build_model.py"),
        "--config",
        str(config_path),
        "--input",
        str(input_path),
        "--output",
        str(output),
    ]
    region_command = [
        python,
        str(WORKFLOW_DIR / "plot_region_yields.py"),
        "--output",
        str(output),
    ]
    tf_command = [
        python,
        str(WORKFLOW_DIR / "plot_transfer_factors.py"),
        "--output",
        str(output),
    ]
    limit_command = [
        python,
        str(WORKFLOW_DIR / "run_limits.py"),
        "--output",
        str(output),
        "--workers",
        str(args.workers),
    ]
    if combine_prefix is not None:
        limit_command.extend(["--combine-prefix", str(combine_prefix)])
    if args.force:
        limit_command.append("--force")

    interpolation_subdirectory = (
        "interpolation"
        if args.shell_mode == "all"
        else "interpolation_on_shell_only"
    )
    interpolation_command = [
        python,
        str(WORKFLOW_DIR / "interpolate_limits.py"),
        "--output",
        str(output),
        "--shell-mode",
        args.shell_mode,
        "--subdirectory",
        interpolation_subdirectory,
    ]
    impact_command = [
        python,
        str(WORKFLOW_DIR / "run_impacts.py"),
        "--output",
        str(output),
        "--signal",
        benchmark_source,
        "--workers",
        str(args.workers),
    ]
    if combine_prefix is not None:
        impact_command.extend(["--combine-prefix", str(combine_prefix)])
    if args.force:
        impact_command.append("--force")

    stage_status = {stage: "not-selected" for stage in STAGES}
    build_changed = False
    if "build" in selected_stages:
        print("\n[build] Building pass/fail templates and datacards")
        build_ready = resuming and build_products_are_current(output, input_path)
        if build_ready and not args.force:
            print("Reusing input-matched templates and datacards")
            stage_status["build"] = "reused"
        else:
            run(build_command, dry_run=args.dry_run)
            stage_status["build"] = "planned" if args.dry_run else "completed"
            build_changed = not args.dry_run

    if not args.dry_run and not (output / "manifest.json").is_file():
        raise SystemExit(
            "A model manifest is required. Include the build stage or point --output "
            "to an existing workflow directory."
        )
    benchmark_label = (
        check_benchmark(output, benchmark_source) if not args.dry_run else None
    )

    if "plots" in selected_stages:
        print("\n[plots] Plotting pass/fail SR/control regions and transfer factors")
        region_ready = (
            resuming
            and not build_changed
            and plot_products_are_complete(
                output / "plots" / "regions" / "manifest.json", output, 16
            )
        )
        tf_ready = (
            resuming
            and not build_changed
            and plot_products_are_complete(
                output / "plots" / "transfer_factors" / "manifest.json", output, 8
            )
        )
        if region_ready and not args.force:
            print("Reusing complete region plots")
        else:
            run(region_command, dry_run=args.dry_run)
        if tf_ready and not args.force:
            print("Reusing complete transfer-factor plots")
        else:
            run(tf_command, dry_run=args.dry_run)
        stage_status["plots"] = (
            "reused"
            if region_ready and tf_ready and not args.force
            else "planned"
            if args.dry_run
            else "completed"
        )

    if "limits" in selected_stages:
        print("\n[limits] Calculating blinded expected limits")
        limits_ready = resuming and not build_changed and limit_products_are_complete(output)
        if limits_ready and not args.force:
            print("Reusing complete blinded expected-limit products")
            stage_status["limits"] = "reused"
        else:
            if build_changed and "--force" not in limit_command:
                limit_command.append("--force")
            run(limit_command, dry_run=args.dry_run)
            stage_status["limits"] = "planned" if args.dry_run else "completed"

    if "interpolation" in selected_stages:
        print("\n[interpolation] Interpolating and plotting the expected limit")
        run(interpolation_command, dry_run=args.dry_run)
        stage_status["interpolation"] = "planned" if args.dry_run else "completed"

    if "impacts" in selected_stages:
        print("\n[impacts] Calculating blinded nuisance-parameter impacts")
        impact_ready = bool(
            resuming
            and not build_changed
            and benchmark_label
            and (output / "impacts" / f"impacts_{benchmark_label}.json").is_file()
            and (output / "impacts" / f"impacts_{benchmark_label}.pdf").is_file()
            and (
                output / "impacts" / f"impacts_{benchmark_label}_summary.pdf"
            ).is_file()
        )
        if impact_ready and not args.force:
            print("Reusing complete impact products")
            stage_status["impacts"] = "reused"
        else:
            if build_changed and "--force" not in impact_command:
                impact_command.append("--force")
            run(impact_command, dry_run=args.dry_run)
            stage_status["impacts"] = "planned" if args.dry_run else "completed"

    if args.dry_run:
        if "validate" in selected_stages:
            print("\n[validate] Would check the complete blinded workflow products")
        print("\nDry run complete; no files were written.")
        return

    validation: dict[str, int | str] = {"status": "not-run"}
    if "validate" in selected_stages:
        print("\n[validate] Checking the complete blinded workflow products")
        if benchmark_label is None:
            raise RuntimeError("Internal error: benchmark label was not resolved")
        validation = validate_products(
            output,
            benchmark_label,
            auto_mc_stats_threshold=int(config["auto_mc_stats_threshold"]),
            interpolation_subdirectory=interpolation_subdirectory,
        )
        stage_status["validate"] = "completed"

    summary = {
        "blinded": True,
        "era": era,
        "luminosity_fb": luminosity_fb,
        "input": str(input_path),
        "input_sha256": file_sha256(input_path),
        "output": str(output),
        "shell_mode": args.shell_mode,
        "stages": stage_status,
        "validation": validation,
        "products": {
            "region_plots": "plots/regions/manifest.json",
            "transfer_factor_table": "transfer_factors.csv",
            "transfer_factor_plots": "plots/transfer_factors/manifest.json",
            "templates": "templates/templates.root",
            "datacards": "datacards/",
            "limits": "limits/limits.csv",
            "limit_plot": f"{interpolation_subdirectory}/limit_interpolation.pdf",
            "impacts": f"impacts/impacts_{benchmark_label}.pdf",
            "impact_summary": f"impacts/impacts_{benchmark_label}_summary.pdf",
        },
    }
    summary_path = output / "workflow_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nDone. Summary: {summary_path}")


if __name__ == "__main__":
    main()
