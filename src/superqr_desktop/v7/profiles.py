from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json


@dataclass(frozen=True)
class OpticalProfile:
    id: int
    key: str
    label: str
    qr_version: int
    qr_ecc: str
    qr_mask: int
    frame_size: int
    payload_size: int


def _load_production_profiles() -> tuple[OpticalProfile, ...]:
    contract = json.loads(
        resources.files("superqr_desktop.contract")
        .joinpath("v7_production_qr_contract.json")
        .read_text(encoding="utf-8")
    )
    if contract.get("status") != "PRODUCTION_COMPATIBILITY_FROZEN":
        raise RuntimeError("invalid production QR compatibility contract")
    return tuple(
        OpticalProfile(
            id=int(item["id"]),
            key=str(item["key"]),
            label=f"V40-{item['qr_ecc']} {item['sender_fps']}fps",
            qr_version=int(item["qr_version"]),
            qr_ecc=str(item["qr_ecc"]),
            qr_mask=int(contract["optical"]["mask_pattern"]),
            frame_size=int(item["frame_bytes"]),
            payload_size=int(item["payload_bytes"]),
        )
        for item in contract["profiles"]
    )


PROFILES = _load_production_profiles()

BY_ID = {p.id: p for p in PROFILES}
BY_KEY = {p.key: p for p in PROFILES}
BY_LABEL = {p.label: p for p in PROFILES}

# Physical captures currently establish V40-L 15 FPS as the reliable baseline.
# Faster V40 modes remain explicit user-selectable experiments until physical
# transfer tests prove they should replace the default.
DEFAULT_PROFILE = BY_KEY["v40_l_15fps"]


def get_profile(value: int | str | OpticalProfile) -> OpticalProfile:
    if isinstance(value, OpticalProfile):
        return value
    if isinstance(value, int):
        return BY_ID[value]
    if value in BY_KEY:
        return BY_KEY[value]
    if value in BY_LABEL:
        return BY_LABEL[value]
    raise KeyError(f"unknown V7 optical profile: {value}")
