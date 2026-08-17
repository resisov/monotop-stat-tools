#!/usr/bin/env python3
"""Shared helpers for the Run 3 monotop statistical workflows."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "analysis_2022preEE.json"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "2022preEE"
SIGNAL_RE = re.compile(r"^sig_Mphi-(?P<mphi>\d+)_Mchi-(?P<mchi>\d+)$")


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with Path(path).open() as handle:
        return json.load(handle)


def signal_metadata(name: str) -> dict[str, int | str]:
    match = SIGNAL_RE.match(name)
    if not match:
        raise ValueError(f"Unrecognised signal name: {name}")
    mphi = int(match.group("mphi"))
    mchi = int(match.group("mchi"))
    return {
        "source_name": name,
        "template_name": f"signal_mphi{mphi}_mchi{mchi}",
        "label": f"mphi{mphi}_mchi{mchi}",
        "mphi": mphi,
        "mchi": mchi,
    }


def ensure_directories(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def combine_environment(prefix: str | Path | None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("XDG_CACHE_HOME", "/tmp/codex-monotop-cache")
    if prefix is None:
        return env
    prefix_path = Path(prefix).resolve()
    python_dirs = sorted((prefix_path / "lib").glob("python*/site-packages"))
    path_parts = [str(prefix_path / "bin"), env.get("PATH", "")]
    env["PATH"] = os.pathsep.join(path_parts)
    if python_dirs:
        current = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            [str(python_dirs[-1]), current] if current else [str(python_dirs[-1])]
        )
    return env


def run_command(
    command: Sequence[str],
    *,
    cwd: str | Path,
    log_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        cwd=Path(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.stdout)
    if result.returncode:
        tail = "\n".join(result.stdout.splitlines()[-40:])
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}\n{tail}"
        )
    return result


def write_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
