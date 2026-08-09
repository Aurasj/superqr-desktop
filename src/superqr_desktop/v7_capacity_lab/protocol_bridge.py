"""Access to V7 Capacity Lab protocol definitions.

NORMAL RUNTIME:
    Uses packaged canonical JSON data and local Desktop implementations.
    No sibling superqr-protocol repository required.

OPTIONAL DEVELOPMENT CHECK:
    When SUPERQR_PROTOCOL_ROOT is set or the expected sibling repository
    exists, the protocol Python modules can be imported for comparison.
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
_protocol_available: bool | None = None
_reference_vectors_cache: dict | None = None
_v6_contract_cache: dict | None = None
_phy_selection_manifest_cache: dict | None = None


# ── Path resolution ──────────────────────────────────────────────────────

def _find_desktop_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _get_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def _try_find_protocol_root() -> Path | None:
    env_root = os.environ.get("SUPERQR_PROTOCOL_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if _is_valid_protocol_root(candidate):
            return candidate

    desktop_root = _find_desktop_root()
    sibling = desktop_root.parent / "superqr-protocol"
    if sibling.is_dir() and _is_valid_protocol_root(sibling):
        return sibling

    return None


def _is_valid_protocol_root(root: Path) -> bool:
    return (
        (root / "protocol" / "v7_capacity_lab").is_dir()
        and (root / "test-vectors" / "v7-capacity-lab" / "reference_vectors.json").is_file()
    )


def is_protocol_repo_available() -> bool:
    global _protocol_available
    if _protocol_available is None:
        _protocol_available = _try_find_protocol_root() is not None
    return _protocol_available


def get_protocol_root() -> Path | None:
    """Return the protocol repo root, or None if unavailable."""
    global _protocol_root
    if _protocol_root is None:
        _protocol_root = _try_find_protocol_root()
        if _protocol_root is not None and str(_protocol_root) not in sys.path:
            sys.path.insert(0, str(_protocol_root))
    return _protocol_root


# ── JSON data loading (from packaged data or protocol repo) ───────────────

def load_reference_vectors() -> dict[str, Any]:
    global _reference_vectors_cache
    if _reference_vectors_cache is None:
        root = get_protocol_root()
        if root is not None:
            path = root / "test-vectors" / "v7-capacity-lab" / "reference_vectors.json"
        else:
            path = _get_data_dir() / "reference_vectors.json"
        with open(path, "r", encoding="utf-8") as f:
            _reference_vectors_cache = json.load(f)
    return _reference_vectors_cache


def load_v6_visual_contract() -> dict[str, Any]:
    global _v6_contract_cache
    if _v6_contract_cache is None:
        root = get_protocol_root()
        if root is not None:
            path = root / "protocol" / "v6" / "visual_contract.json"
        else:
            path = _get_data_dir() / "v6_visual_contract.json"
        with open(path, "r", encoding="utf-8") as f:
            _v6_contract_cache = json.load(f)
    return _v6_contract_cache


def load_phy_selection_manifest() -> dict[str, Any]:
    """Load the canonical laboratory-only Phase 1 PHY manifest."""
    global _phy_selection_manifest_cache
    if _phy_selection_manifest_cache is None:
        root = get_protocol_root()
        if root is not None:
            path = root / "test-vectors" / "v7-phy-selection" / "phase1_manifest.json"
        else:
            path = _get_data_dir() / "phase1_manifest.json"
        with open(path, "r", encoding="utf-8") as f:
            _phy_selection_manifest_cache = json.load(f)
    return _phy_selection_manifest_cache


# ── Module access (local or protocol repo) ────────────────────────────────

def get_protocol_model():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.model", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import model
    return model


def get_protocol_palettes():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.palettes", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import palettes
    return palettes


def get_protocol_profiles():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.profiles", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import profiles
    return profiles


def get_protocol_patterns():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.patterns", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import patterns
    return patterns


def get_protocol_geometry():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.geometry", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import geometry
    return geometry


def get_protocol_layouts():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.layouts", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import layouts
    return layouts


def get_protocol_vectors():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.vectors", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import vectors
    return vectors


def get_protocol_calibration():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.calibration", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import calibration
    return calibration


def get_protocol_prng():
    root = get_protocol_root()
    if root is not None:
        return __import__("protocol.v7_capacity_lab.prng", fromlist=["_"])
    from superqr_desktop.v7_capacity_lab._local import prng
    return prng
