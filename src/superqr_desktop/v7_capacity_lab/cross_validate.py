"""Deterministic cross-validation against protocol golden reference vectors.

Before any physical experiment can start, Desktop must confirm the selected
profile agrees with the protocol reference data. A mismatch must fail loudly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from superqr_desktop.v7_capacity_lab.protocol_bridge import (
    load_reference_vectors,
    get_protocol_palettes,
    get_protocol_patterns,
    get_protocol_vectors,
    get_protocol_prng,
    get_protocol_profiles,
)


@dataclass
class ValidationResult:
    profile_name: str
    passed: bool
    checks: dict[str, bool]  # check_name -> passed
    details: dict[str, str]  # check_name -> detail message


def validate_profile(profile) -> ValidationResult:
    """Regenerate symbol matrix and verify against golden vectors.

    Args:
        profile: A LabProfile from protocol.v7_capacity_lab.profiles.

    Returns:
        ValidationResult with per-check pass/fail and detail messages.
    """
    ref_vectors = load_reference_vectors()
    entries = ref_vectors.get("vectors", {})

    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    # 1. Profile must have a matching reference vector
    if profile.name not in entries:
        checks["reference_found"] = False
        details["reference_found"] = (
            f"Profile '{profile.name}' not found in reference_vectors.json. "
            f"Available: {list(entries.keys())}"
        )
        return ValidationResult(
            profile_name=profile.name, passed=False, checks=checks, details=details
        )
    checks["reference_found"] = True
    details["reference_found"] = f"Profile '{profile.name}' found in reference vectors."

    expected = entries[profile.name]

    # 2. Regenerate reference vector from profile
    vectors_mod = get_protocol_vectors()
    rv = vectors_mod.generate_reference_vector(profile)

    # 3. Scalar field checks
    for key in ["grid_size", "palette_name", "seed", "symbols_per_frame"]:
        actual = getattr(rv, key)
        exp_val = expected[key]
        if actual != exp_val:
            checks[key] = False
            details[key] = f"Expected {exp_val}, got {actual}"
        else:
            checks[key] = True
            details[key] = f"{key}={actual} OK"

    # 4. first_20
    if rv.first_20 != expected["first_20"]:
        checks["first_20"] = False
        details["first_20"] = (
            f"First 20 mismatch:\n  expected: {expected['first_20']}\n  got:      {rv.first_20}"
        )
    else:
        checks["first_20"] = True
        details["first_20"] = "first_20 OK"

    # 5. last_20
    if rv.last_20 != expected["last_20"]:
        checks["last_20"] = False
        details["last_20"] = (
            f"Last 20 mismatch:\n  expected: {expected['last_20']}\n  got:      {rv.last_20}"
        )
    else:
        checks["last_20"] = True
        details["last_20"] = "last_20 OK"

    # 6. symbol_crc32
    if rv.symbol_crc32 != expected["symbol_crc32"]:
        checks["symbol_crc32"] = False
        details["symbol_crc32"] = (
            f"CRC32 mismatch: expected {expected['symbol_crc32']}, got {rv.symbol_crc32}"
        )
    else:
        checks["symbol_crc32"] = True
        details["symbol_crc32"] = f"CRC32={rv.symbol_crc32} OK"

    # 7. symbol_sha256
    if rv.symbol_sha256 != expected["symbol_sha256"]:
        checks["symbol_sha256"] = False
        details["symbol_sha256"] = (
            f"SHA-256 mismatch: expected {expected['symbol_sha256']}, got {rv.symbol_sha256}"
        )
    else:
        checks["symbol_sha256"] = True
        details["symbol_sha256"] = f"SHA-256={rv.symbol_sha256[:16]}... OK"

    # 8. Full matrix re-derivation from scratch
    patterns_mod = get_protocol_patterns()
    palettes_mod = get_protocol_palettes()
    prng_mod = get_protocol_prng()

    palette = palettes_mod.get_palette(profile.palette_name)
    prng = prng_mod.Xorshift32(profile.seed)
    matrix = patterns_mod.random_fill(
        prng, profile.grid_size, profile.grid_size,
        palette.name, palette.bits_per_cell,
    )

    matrix_ok = vectors_mod.verify_symbol_matrix_from_reference(rv, matrix)
    checks["full_matrix_hashes"] = matrix_ok
    if matrix_ok:
        details["full_matrix_hashes"] = "Full matrix CRC32 and SHA-256 verified OK"
    else:
        details["full_matrix_hashes"] = (
            "Full matrix hash verification FAILED — Desktop regeneration "
            "does not match protocol golden vectors"
        )

    passed = all(checks.values())
    return ValidationResult(
        profile_name=profile.name, passed=passed, checks=checks, details=details
    )


def validate_reference_profiles() -> list[ValidationResult]:
    """Validate all 14 standard reference profiles.

    Returns:
        List of ValidationResult, one per reference profile.
    """
    profiles_mod = get_protocol_profiles()
    profiles = profiles_mod.build_reference_profiles()
    results = []
    for profile in profiles:
        result = validate_profile(profile)
        results.append(result)
    return results


def validate_or_fail(profile) -> None:
    """Validate a profile and exit with code 1 on any mismatch.

    Prints detailed pass/fail for each check.
    """
    result = validate_profile(profile)
    _print_result(result)
    if not result.passed:
        print(f"\nCROSS-VALIDATION FAILED for profile '{profile.name}'.")
        print("Desktop output would not agree with protocol reference vectors.")
        print("Refusing to render potentially incompatible experimental data.")
        sys.exit(1)
    print(f"\nCross-validation PASSED for profile '{profile.name}'.")


def _print_result(result: ValidationResult) -> None:
    """Print a validation result with per-check details."""
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {result.profile_name}")
    for check_name, ok in result.checks.items():
        mark = "OK" if ok else "FAIL"
        detail = result.details.get(check_name, "")
        print(f"  [{mark}] {check_name}")
        if not ok and detail:
            for line in detail.split("\n"):
                print(f"        {line}")


def main() -> None:
    """Standalone: validate all reference profiles."""
    print("V7 Capacity Lab — Cross-Validation\n")
    results = validate_reference_profiles()

    all_passed = all(r.passed for r in results)
    print()
    for r in results:
        _print_result(r)
        print()

    print(f"{'='*60}")
    if all_passed:
        print(f"All {len(results)} reference profiles validated successfully.")
    else:
        failed = [r for r in results if not r.passed]
        print(f"{len(failed)}/{len(results)} profiles FAILED validation.")
        print("Failed profiles:")
        for r in failed:
            print(f"  - {r.profile_name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
