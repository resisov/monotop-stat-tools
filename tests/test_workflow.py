from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "workflow"))

import run_simple
from common import signal_metadata


class WorkflowCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.pop("COMBINE_PREFIX", None)
        environment.pop("CONDA_PREFIX", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "run_simple.py"), *arguments],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_full_dry_run_needs_no_combine_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            input_path = temporary / "sample.scaled"
            input_path.write_bytes(b"dry-run input")
            output = temporary / "products"

            result = self.run_cli(
                "--input",
                str(input_path),
                "--era",
                "test-era",
                "--lumi",
                "1.0",
                "--output",
                str(output),
                "--dry-run",
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("run_limits.py", result.stdout)
            self.assertIn("run_impacts.py", result.stdout)
            self.assertIn("Dry run complete", result.stdout)
            self.assertFalse(output.exists())

    def test_config_input_is_resolved_relative_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            config_directory = temporary / "config"
            input_directory = temporary / "inputs"
            config_directory.mkdir()
            input_directory.mkdir()
            input_path = input_directory / "sample.scaled"
            input_path.write_bytes(b"portable input")
            config = run_simple.default_analysis_config(
                era="portable",
                luminosity_fb=2.5,
                input_path=input_path,
                benchmark="sig_Mphi-1000_Mchi-150",
                luminosity_uncertainty=1.02,
            )
            config["input"] = "../inputs/sample.scaled"
            config_path = config_directory / "analysis.json"
            config_path.write_text(json.dumps(config))

            result = self.run_cli(
                "--config",
                str(config_path),
                "--output",
                str(temporary / "products"),
                "--stages",
                "build",
                "plots",
                "--dry-run",
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn(str(input_path), result.stdout)


class WorkflowStateTests(unittest.TestCase):
    def test_build_cache_is_invalidated_when_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            input_path = temporary / "sample.scaled"
            input_path.write_bytes(b"first")
            output = temporary / "output"
            (output / "templates").mkdir(parents=True)
            (output / "datacards").mkdir()
            (output / "templates" / "templates.root").write_bytes(b"root")
            (output / "datacards" / "datacard_point.txt").write_text("card")
            (output / "manifest.json").write_text(
                json.dumps(
                    {
                        "input_sha256": run_simple.file_sha256(input_path),
                        "signals": [{"source_name": "point"}],
                    }
                )
            )

            self.assertTrue(run_simple.build_products_are_current(output, input_path))
            input_path.write_bytes(b"second")
            self.assertFalse(run_simple.build_products_are_current(output, input_path))

    def test_signal_metadata_is_canonical(self) -> None:
        self.assertEqual(
            signal_metadata("sig_Mphi-1000_Mchi-150"),
            {
                "source_name": "sig_Mphi-1000_Mchi-150",
                "template_name": "signal_mphi1000_mchi150",
                "label": "mphi1000_mchi150",
                "mphi": 1000,
                "mchi": 150,
            },
        )


if __name__ == "__main__":
    unittest.main()
