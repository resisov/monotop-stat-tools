#!/usr/bin/env python3
"""Shared mplhep styling for all monotop plots."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/codex-monotop-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplhep as hep


CMS_LLABEL = "Work in progress"
MODEL_LABEL = "Vector mediator\n" + r"$g_q = 0.25,\ g_{\mathrm{DM}} = 1.0$"


def use_cms_style() -> None:
    """Apply the common CMS mplhep style."""

    plt.style.use(hep.style.CMS)


def cms_label(axis: plt.Axes, luminosity_fb: float) -> None:
    """Draw the only allowed CMS label."""

    hep.cms.label(
        llabel=CMS_LLABEL,
        rlabel=rf"{luminosity_fb:g} fb$^{{-1}}$ (13.6 TeV)",
        ax=axis,
    )


def save_png_pdf(figure: plt.Figure, base_path: Path, *, dpi: int = 180) -> None:
    """Save a figure under the same basename as PNG and PDF."""

    figure.savefig(base_path.with_suffix(".png"), dpi=dpi)
    figure.savefig(base_path.with_suffix(".pdf"))
