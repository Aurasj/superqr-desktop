"""Local layout builders matching protocol.v7_capacity_lab.layouts.

CONSUMER IMPLEMENTATION — NOT a second source of truth.
"""

from superqr_desktop.v7_capacity_lab._local.model import (
    PayloadLayout, PayloadRegion, GridGeometry,
)


def build_single_region(geometry: GridGeometry) -> PayloadLayout:
    region = PayloadRegion(
        region_id=0, row_start=0, row_end=geometry.rows,
        col_start=0, col_end=geometry.cols,
    )
    return PayloadLayout(name="single", regions=[region])


def build_2x2_regions(geometry: GridGeometry) -> PayloadLayout:
    r_mid = geometry.rows // 2
    c_mid = geometry.cols // 2
    r_split = [0, r_mid, geometry.rows]
    c_split = [0, c_mid, geometry.cols]

    regions = []
    reg_id = 0
    for ri in range(2):
        for ci in range(2):
            region = PayloadRegion(
                region_id=reg_id,
                row_start=r_split[ri], row_end=r_split[ri + 1],
                col_start=c_split[ci], col_end=c_split[ci + 1],
            )
            regions.append(region)
            reg_id += 1
    return PayloadLayout(name="2x2", regions=regions)


LAYOUT_BUILDERS = {"single": build_single_region, "2x2": build_2x2_regions}


def get_layout(name: str, geometry: GridGeometry) -> PayloadLayout:
    if name not in LAYOUT_BUILDERS:
        raise KeyError(f"Unknown layout: {name}. Available: {list(LAYOUT_BUILDERS.keys())}")
    return LAYOUT_BUILDERS[name](geometry)
