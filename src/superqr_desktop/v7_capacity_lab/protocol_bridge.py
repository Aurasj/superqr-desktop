"""Centralized access to the sibling superqr-protocol repository.

Every V7 Capacity Lab Desktop module imports protocol definitions
through this bridge. No other module may manipulate sys.path or
resolve protocol paths independently.

Resolution order:
    1. SUPERQR_PROTOCOL_ROOT environment variable
    2. Expected sibling repository in the SuperQR workspace
    3. Clear actionable error
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


class ProtocolBridgeError(Exception):
    """The superqr-protocol repository could not be located or is invalid."""


_protocol_root: Path | None = None
_reference_vectors_cache: dict | None = None
_v6_contract_cache: dict | None = None


def _find_desktop_root() -> Path:
    """Find the superqr-desktop repository root from this file's location."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _resolve_protocol_root() -> Path:
    """Locate and validate the superqr-protocol repository root."""
    # 1. Environment variable
    env_root = os.environ.get("SUPERQR_PROTOCOL_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        _validate_protocol_root(candidate)
        return candidate

    # 2. Expected sibling in SuperQR workspace
    desktop_root = _find_desktop_root()
    workspace = desktop_root.parent  # superqr-desktop is one child of the workspace
    sibling = workspace / "superqr-protocol"
    if sibling.is_dir():
        _validate_protocol_root(sibling)
        return sibling

    # 3. Failure
    raise ProtocolBridgeError(
        "Cannot locate superqr-protocol repository.\n"
        "\n"
        "Tried:\n"
        f"  - SUPERQR_PROTOCOL_ROOT environment variable (not set)\n"
        f"  - Expected sibling: {sibling} (not found)\n"
        "\n"
        "Set SUPERQR_PROTOCOL_ROOT to the superqr-protocol repository path\n"
        "or clone it as a sibling of superqr-desktop in the SuperQR workspace."
    )


def _validate_protocol_root(root: Path) -> None:
    """Verify the resolved root contains required protocol directories."""
    missing = []
    if not (root / "protocol" / "v7_capacity_lab").is_dir():
        missing.append("protocol/v7_capacity_lab/")
    if not (root / "test-vectors" / "v7-capacity-lab" / "reference_vectors.json").is_file():
        missing.append("test-vectors/v7-capacity-lab/reference_vectors.json")
    if not (root / "protocol" / "v6" / "visual_contract.json").is_file():
        missing.append("protocol/v6/visual_contract.json")
    if missing:
        raise ProtocolBridgeError(
            f"superqr-protocol at {root} is missing required paths:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


def get_protocol_root() -> Path:
    """Return the resolved superqr-protocol repository root."""
    global _protocol_root
    if _protocol_root is None:
        _protocol_root = _resolve_protocol_root()
        # Add to sys.path so protocol package is importable
        sys.path.insert(0, str(_protocol_root))
    return _protocol_root


def _import_module(name: str):
    """Import and return a protocol module by dotted name."""
    get_protocol_root()  # ensure sys.path is set up
    return __import__(name, fromlist=["_"])


def get_protocol_model():
    """Return protocol.v7_capacity_lab.model module."""
    return _import_module("protocol.v7_capacity_lab.model")


def get_protocol_palettes():
    """Return protocol.v7_capacity_lab.palettes module."""
    return _import_module("protocol.v7_capacity_lab.palettes")


def get_protocol_profiles():
    """Return protocol.v7_capacity_lab.profiles module."""
    return _import_module("protocol.v7_capacity_lab.profiles")


def get_protocol_patterns():
    """Return protocol.v7_capacity_lab.patterns module."""
    return _import_module("protocol.v7_capacity_lab.patterns")


def get_protocol_geometry():
    """Return protocol.v7_capacity_lab.geometry module."""
    return _import_module("protocol.v7_capacity_lab.geometry")


def get_protocol_layouts():
    """Return protocol.v7_capacity_lab.layouts module."""
    return _import_module("protocol.v7_capacity_lab.layouts")


def get_protocol_vectors():
    """Return protocol.v7_capacity_lab.vectors module."""
    return _import_module("protocol.v7_capacity_lab.vectors")


def get_protocol_calibration():
    """Return protocol.v7_capacity_lab.calibration module."""
    return _import_module("protocol.v7_capacity_lab.calibration")


def get_protocol_prng():
    """Return protocol.v7_capacity_lab.prng module."""
    return _import_module("protocol.v7_capacity_lab.prng")


def load_reference_vectors() -> dict[str, Any]:
    """Load and cache the protocol golden reference vectors."""
    global _reference_vectors_cache
    if _reference_vectors_cache is None:
        root = get_protocol_root()
        path = root / "test-vectors" / "v7-capacity-lab" / "reference_vectors.json"
        with open(path, "r", encoding="utf-8") as f:
            _reference_vectors_cache = json.load(f)
    return _reference_vectors_cache


def load_v6_visual_contract() -> dict[str, Any]:
    """Load and cache the canonical V6 visual contract.

    Used only as V6_REFERENCE_LAB_CARRIER — temporary laboratory scaffolding.
    Does NOT define final V7 geometry.
    """
    global _v6_contract_cache
    if _v6_contract_cache is None:
        root = get_protocol_root()
        path = root / "protocol" / "v6" / "visual_contract.json"
        with open(path, "r", encoding="utf-8") as f:
            _v6_contract_cache = json.load(f)
    return _v6_contract_cache
