#!/usr/bin/env python3
"""Combine matching signal datacards from multiple era output directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        metavar="LABEL=OUTPUT",
        help="Component label and completed era output directory; repeat per era",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def parse_inputs(values: list[str]) -> list[tuple[str, Path]]:
    parsed: list[tuple[str, Path]] = []
    labels: set[str] = set()
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --input {value!r}; expected LABEL=OUTPUT")
        label, raw_path = value.split("=", 1)
        if not LABEL_PATTERN.fullmatch(label):
            raise SystemExit(f"Invalid component label {label!r}")
        if label in labels:
            raise SystemExit(f"Duplicate component label {label!r}")
        path = Path(raw_path).expanduser().resolve()
        if not (path / "manifest.json").is_file():
            raise SystemExit(f"Missing manifest: {path / 'manifest.json'}")
        labels.add(label)
        parsed.append((label, path))
    if len(parsed) < 2:
        raise SystemExit("At least two component outputs are required")
    return parsed


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("signals"), list):
        raise SystemExit(f"Invalid workflow manifest: {path}")
    return payload


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    components = parse_inputs(args.input)
    output = args.output.expanduser().resolve()
    datacard_dir = output / "datacards"
    log_dir = output / "logs"
    datacard_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    manifests = [(label, path, load_manifest(path / "manifest.json")) for label, path in components]
    signal_maps = [
        {str(signal["source_name"]): signal for signal in manifest["signals"]}
        for _label, _path, manifest in manifests
    ]
    common_sources = set.intersection(*(set(signal_map) for signal_map in signal_maps))
    if not common_sources:
        raise SystemExit("The component outputs have no common signal mass points")

    reference = signal_maps[0]
    ordered_sources = sorted(
        common_sources,
        key=lambda source: (int(reference[source]["mphi"]), int(reference[source]["mchi"])),
    )
    combined_signals: list[dict[str, Any]] = []
    expected_card_names: set[str] = set()
    for index, source in enumerate(ordered_sources, start=1):
        component_signals = [signal_map[source] for signal_map in signal_maps]
        labels = {str(signal["label"]) for signal in component_signals}
        masses = {(int(signal["mphi"]), int(signal["mchi"])) for signal in component_signals}
        if len(labels) != 1 or len(masses) != 1:
            raise RuntimeError(f"Inconsistent signal metadata for {source}")
        signal_label = labels.pop()
        card_name = f"datacard_{signal_label}.txt"
        expected_card_names.add(card_name)
        card_path = datacard_dir / card_name
        log_path = log_dir / f"combine_cards_{signal_label}.log"
        command = ["combineCards.py"]
        component_cards: dict[str, str] = {}
        for (component_label, component_path, _manifest), signal in zip(
            manifests, component_signals
        ):
            source_card = (component_path / str(signal["datacard"])).resolve()
            if not source_card.is_file():
                raise RuntimeError(f"Missing component datacard: {source_card}")
            component_cards[component_label] = str(source_card)
            command.append(f"{component_label}={source_card}")
        if args.force or not card_path.is_file():
            completed = subprocess.run(
                command,
                cwd=output,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            log_path.write_text(completed.stderr)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"combineCards.py failed for {signal_label}; see {log_path}"
                )
            card_path.write_text(completed.stdout)
        if not card_path.is_file() or card_path.stat().st_size == 0:
            raise RuntimeError(f"Combined datacard was not created: {card_path}")

        mass_mediator, mass_dark_matter = masses.pop()
        combined_signals.append(
            {
                "source_name": source,
                "label": signal_label,
                "mphi": mass_mediator,
                "mchi": mass_dark_matter,
                "datacard": str(card_path.relative_to(output)),
                "sr_signal_yield": sum(
                    float(signal["sr_signal_yield"]) for signal in component_signals
                ),
                "recommended_rmax": min(
                    float(signal["recommended_rmax"]) for signal in component_signals
                ),
                "component_datacards": component_cards,
            }
        )
        print(f"[{index:02d}/{len(ordered_sources):02d}] {signal_label}", flush=True)

    for stale_card in datacard_dir.glob("datacard_*.txt"):
        if stale_card.name not in expected_card_names:
            stale_card.unlink()

    luminosity_fb = sum(float(manifest["luminosity_fb"]) for _, _, manifest in manifests)
    component_payload = []
    for label, path, manifest in manifests:
        manifest_path = path / "manifest.json"
        component_payload.append(
            {
                "label": label,
                "era": manifest["era"],
                "luminosity_fb": float(manifest["luminosity_fb"]),
                "output": str(path),
                "manifest": str(manifest_path),
                "manifest_sha256": file_sha256(manifest_path),
                "n_signal_points": len(manifest["signals"]),
            }
        )
    manifest = {
        "analysis": "hadronic_monotop",
        "era": "+".join(str(item["era"]) for item in component_payload),
        "luminosity_fb": luminosity_fb,
        "components": component_payload,
        "combination": "intersection of signal points present in every component era",
        "n_common_signal_points": len(combined_signals),
        "signals": combined_signals,
        "model_scope": (
            "Blinded expected-only multi-era combination with independent era channels "
            "and era-specific luminosity nuisances. Impacts are not evaluated."
        ),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Wrote {len(combined_signals)} combined datacards for {luminosity_fb:.2f} fb^-1 "
        f"to {output}",
        flush=True,
    )


if __name__ == "__main__":
    main()
