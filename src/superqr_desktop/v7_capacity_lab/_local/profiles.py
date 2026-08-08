"""Local profile/sequence builders matching protocol.v7_capacity_lab.profiles.

CONSUMER IMPLEMENTATION — NOT a second source of truth.
"""

from superqr_desktop.v7_capacity_lab._local.model import (
    LabProfile, LabFrame, FrameSequence, CalibrationConfig,
)
from superqr_desktop.v7_capacity_lab._local.prng import Xorshift32
from superqr_desktop.v7_capacity_lab._local.palettes import get_palette
from superqr_desktop.v7_capacity_lab._local.geometry import build_geometry
from superqr_desktop.v7_capacity_lab._local.layouts import get_layout
from superqr_desktop.v7_capacity_lab._local.patterns import random_fill
from superqr_desktop.v7_capacity_lab._local.calibration import build_solid_calibration_frames

GRID_SIZES = [40, 48, 56, 64, 72, 80, 96]
DEFAULT_SEED = 42


def build_profile(
    name: str, grid_size: int, palette_name: str,
    layout_name: str = "single", seed: int = DEFAULT_SEED,
    dwell_epochs: int = 2, calibration: CalibrationConfig | None = None,
) -> LabProfile:
    get_palette(palette_name)
    build_geometry(grid_size)
    get_layout(layout_name, build_geometry(grid_size))
    if calibration is None:
        calibration = CalibrationConfig()
    return LabProfile(
        name=name, grid_size=grid_size, palette_name=palette_name,
        layout_name=layout_name, seed=seed, dwell_epochs=dwell_epochs,
        calibration=calibration,
    )


def build_frame_sequence(profile: LabProfile, num_data_frames: int) -> FrameSequence:
    palette = get_palette(profile.palette_name)
    geometry = build_geometry(profile.grid_size)
    prng = Xorshift32(profile.seed)

    frames: list[LabFrame] = []
    logical_epoch = 0

    if profile.calibration.solid_frames:
        cal_frames = build_solid_calibration_frames(
            palette, geometry, base_logical_epoch=logical_epoch,
            dwell_epochs=profile.dwell_epochs,
        )
        frames.extend(cal_frames)
        if cal_frames:
            logical_epoch = cal_frames[-1].logical_epoch + profile.dwell_epochs

    for i in range(num_data_frames):
        matrix = random_fill(prng, geometry.rows, geometry.cols,
                             palette.name, palette.bits_per_cell)
        frame = LabFrame(
            frame_index=len(frames), frame_type="data",
            symbol_matrix=matrix, dwell_epochs=profile.dwell_epochs,
            logical_epoch=logical_epoch, is_calibration=False,
        )
        frames.append(frame)
        logical_epoch += profile.dwell_epochs

    return FrameSequence(profile_name=profile.name, frames=frames)


def build_reference_profiles() -> list[LabProfile]:
    profiles = []
    for grid_size in GRID_SIZES:
        for palette_name in ["v6_reference_4", "candidate_8_a"]:
            name = f"ref_{grid_size}x{grid_size}_{palette_name}_seed{DEFAULT_SEED}"
            profile = build_profile(
                name=name, grid_size=grid_size, palette_name=palette_name,
                layout_name="single", seed=DEFAULT_SEED, dwell_epochs=2,
            )
            profiles.append(profile)
    return profiles
