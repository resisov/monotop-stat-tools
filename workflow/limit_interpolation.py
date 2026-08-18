#!/usr/bin/env python3
"""Physics-aware helpers for interpolating monotop expected limits."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import LinearNDInterpolator


SHELL_MODES = ("all", "on-shell-only", "off-shell-only")


def beta_chi(mediator_mass: np.ndarray, dark_matter_mass: np.ndarray) -> np.ndarray:
    """Return the on-shell dark-matter velocity factor.

    Values at and below threshold are returned as NaN because they do not
    belong to the strict mV > 2*mX interpolation domain.
    """

    mediator = np.asarray(mediator_mass, dtype=float)
    dark_matter = np.asarray(dark_matter_mass, dtype=float)
    mediator, dark_matter = np.broadcast_arrays(mediator, dark_matter)
    result = np.full(mediator.shape, np.nan, dtype=float)
    on_shell = (
        np.isfinite(mediator)
        & np.isfinite(dark_matter)
        & (mediator > 0.0)
        & (dark_matter >= 0.0)
        & (mediator > 2.0 * dark_matter)
    )
    ratio = np.zeros_like(mediator, dtype=float)
    np.divide(2.0 * dark_matter, mediator, out=ratio, where=on_shell)
    result[on_shell] = np.sqrt(np.clip(1.0 - ratio[on_shell] ** 2, 0.0, 1.0))
    return result


def kappa_chi(mediator_mass: np.ndarray, dark_matter_mass: np.ndarray) -> np.ndarray:
    """Return the off-shell distance from the mediator-decay threshold.

    Values at and above threshold are returned as NaN so on-shell and
    off-shell mass points can never share an interpolation simplex.
    """

    mediator = np.asarray(mediator_mass, dtype=float)
    dark_matter = np.asarray(dark_matter_mass, dtype=float)
    mediator, dark_matter = np.broadcast_arrays(mediator, dark_matter)
    result = np.full(mediator.shape, np.nan, dtype=float)
    off_shell = (
        np.isfinite(mediator)
        & np.isfinite(dark_matter)
        & (mediator > 0.0)
        & (dark_matter >= 0.0)
        & (mediator < 2.0 * dark_matter)
    )
    ratio = np.zeros_like(mediator, dtype=float)
    np.divide(2.0 * dark_matter, mediator, out=ratio, where=off_shell)
    result[off_shell] = np.sqrt(np.clip(ratio[off_shell] ** 2 - 1.0, 0.0, None))
    return result


def signed_shell_coordinate(
    mediator_mass: np.ndarray,
    dark_matter_mass: np.ndarray,
) -> np.ndarray:
    """Return +beta on shell, -kappa off shell, and zero at threshold."""

    mediator = np.asarray(mediator_mass, dtype=float)
    dark_matter = np.asarray(dark_matter_mass, dtype=float)
    mediator, dark_matter = np.broadcast_arrays(mediator, dark_matter)
    result = np.full(mediator.shape, np.nan, dtype=float)
    physical = (
        np.isfinite(mediator)
        & np.isfinite(dark_matter)
        & (mediator > 0.0)
        & (dark_matter >= 0.0)
    )
    ratio = np.zeros_like(mediator, dtype=float)
    np.divide(2.0 * dark_matter, mediator, out=ratio, where=physical)
    phase_space = 1.0 - ratio[physical] ** 2
    result[physical] = np.sign(phase_space) * np.sqrt(np.abs(phase_space))
    return result


def coordinate_system(shell_mode: str) -> tuple[str, str]:
    if shell_mode == "all":
        return ("mV", "signed_shell_coordinate")
    if shell_mode == "on-shell-only":
        return ("mV", "beta_chi")
    if shell_mode == "off-shell-only":
        return ("mV", "kappa_chi")
    raise ValueError(f"Unknown shell mode: {shell_mode}")


def domain_coordinate_systems(shell_mode: str) -> dict[str, list[str]]:
    systems: dict[str, list[str]] = {}
    if shell_mode == "all":
        systems["combined"] = ["mV", "signed_shell_coordinate"]
    if shell_mode in ("all", "on-shell-only"):
        systems["on_shell"] = ["mV", "beta_chi"]
    if shell_mode in ("all", "off-shell-only"):
        systems["off_shell"] = ["mV", "kappa_chi"]
    if not systems:
        raise ValueError(f"Unknown shell mode: {shell_mode}")
    return systems


def interpolation_coordinates(
    mediator_mass: np.ndarray,
    dark_matter_mass: np.ndarray,
    shell_mode: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Return interpolation coordinates and a physical-domain mask."""

    mediator = np.asarray(mediator_mass, dtype=float)
    dark_matter = np.asarray(dark_matter_mass, dtype=float)
    mediator, dark_matter = np.broadcast_arrays(mediator, dark_matter)
    flat_mediator = mediator.reshape(-1)
    flat_dark_matter = dark_matter.reshape(-1)

    if shell_mode == "all":
        signed_coordinate = signed_shell_coordinate(
            flat_mediator,
            flat_dark_matter,
        )
        valid = np.isfinite(signed_coordinate)
        coordinates = np.column_stack((flat_mediator, signed_coordinate))
    elif shell_mode == "on-shell-only":
        beta = beta_chi(flat_mediator, flat_dark_matter)
        valid = np.isfinite(beta)
        coordinates = np.column_stack((flat_mediator, beta))
    elif shell_mode == "off-shell-only":
        kappa = kappa_chi(flat_mediator, flat_dark_matter)
        valid = np.isfinite(kappa)
        coordinates = np.column_stack((flat_mediator, kappa))
    else:
        raise ValueError(f"Unknown shell mode: {shell_mode}")
    return coordinates, valid


def interpolate_log_surface(
    input_mediator_mass: np.ndarray,
    input_dark_matter_mass: np.ndarray,
    input_values: np.ndarray,
    evaluation_mediator_mass: np.ndarray,
    evaluation_dark_matter_mass: np.ndarray,
    *,
    shell_mode: str,
) -> np.ndarray:
    """Interpolate positive values in log10 space inside the supported hull."""

    values = np.asarray(input_values, dtype=float).reshape(-1)
    evaluation_mediator = np.asarray(evaluation_mediator_mass, dtype=float)
    evaluation_dark_matter = np.asarray(evaluation_dark_matter_mass, dtype=float)
    evaluation_mediator, evaluation_dark_matter = np.broadcast_arrays(
        evaluation_mediator,
        evaluation_dark_matter,
    )
    input_coordinates, input_domain = interpolation_coordinates(
        input_mediator_mass,
        input_dark_matter_mass,
        shell_mode,
    )
    if len(values) != len(input_coordinates):
        raise ValueError("Input masses and values must have matching lengths")
    valid_input = input_domain & np.isfinite(values) & (values > 0.0)
    if np.count_nonzero(valid_input) < 3:
        raise ValueError("At least three valid points are required for interpolation")

    evaluation_coordinates, evaluation_domain = interpolation_coordinates(
        evaluation_mediator,
        evaluation_dark_matter,
        shell_mode,
    )
    result = np.full(evaluation_coordinates.shape[0], np.nan, dtype=float)
    interpolator = LinearNDInterpolator(
        input_coordinates[valid_input],
        np.log10(values[valid_input]),
        fill_value=np.nan,
        rescale=True,
    )
    if np.any(evaluation_domain):
        log_values = interpolator(evaluation_coordinates[evaluation_domain])
        result[evaluation_domain] = np.power(10.0, log_values)
    return result.reshape(evaluation_mediator.shape)
