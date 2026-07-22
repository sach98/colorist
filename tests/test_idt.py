# SPDX-License-Identifier: MIT
import json
from pathlib import Path

import colour
import numpy as np

from colorist.idt import _CURVE_BY_IDT, build_idt, camera_to_working, decode_curve
from colorist.lut import apply_lut


def load_vectors(name: str) -> dict:
    return json.loads(Path(f"tests/vectors/{name}.json").read_text())


def vendor_tolerance(name: str) -> float:
    tolerances = {
        "grey18": 5e-4,
        "black0": 5e-4,
        "white90": 5e-3,
        "signal_zero": 5e-4,
        "signal_f_at_zero": 5e-4,
        "hardware_max": 0.05,
        "sl800": 0.05,
    }
    return tolerances[name]


def test_slog3_decode_matches_colour_science_and_vendor():
    vectors = load_vectors("slog3_sgamut3cine")
    for vector in vectors["vectors"]:
        if "scene_linear_reflectance" not in vector["expected"]:
            continue
        code = vector["code_value_rgb"][0]
        ours = decode_curve("slog3", np.array([code]))[0]
        reference = float(colour.models.log_decoding_SLog3(code))
        assert abs(ours - reference) <= 1e-6, "our decode must equal colour-science"
        assert (
            abs(ours - vector["expected"]["scene_linear_reflectance"])
            <= vendor_tolerance(vector["name"])
        ), f"colour-science disagrees with vendor doc on {vector['name']}"


def test_logc4_decode_matches_colour_science_and_vendor():
    vectors = load_vectors("logc4_awg4")
    for vector in vectors["vectors"]:
        if "scene_linear_reflectance" not in vector["expected"]:
            continue
        code = vector["code_value_rgb"][0]
        ours = decode_curve("logc4", np.array([code]))[0]
        reference = float(colour.models.log_decoding_ARRILogC4(code))
        assert abs(ours - reference) <= 1e-6
        assert (
            abs(ours - vector["expected"]["scene_linear_reflectance"])
            <= vendor_tolerance(vector["name"])
        ), f"colour-science disagrees with vendor doc on {vector['name']}"


def test_vlog_decode_matches_colour_science_and_vendor():
    vectors = load_vectors("vlog_vgamut")
    for vector in vectors["vectors"]:
        if "scene_linear_reflectance" not in vector["expected"]:
            continue
        code = vector["code_value_rgb"][0]
        ours = decode_curve("vlog", np.array([code]))[0]
        reference = float(colour.models.log_decoding_VLog(code))
        assert abs(ours - reference) <= 1e-6, "our decode must equal colour-science"
        assert (
            abs(ours - vector["expected"]["scene_linear_reflectance"])
            <= vendor_tolerance(vector["name"])
        ), f"colour-science disagrees with vendor doc on {vector['name']}"


def test_clog3_decode_matches_colour_science_and_vendor():
    vectors = load_vectors("clog3_cgamut")
    for vector in vectors["vectors"]:
        if "scene_linear_reflectance" not in vector["expected"]:
            continue
        # Canon's displayed Full % values are rounded to 0.1%; use the
        # recorded integer code value to preserve the source-table precision.
        code = vector["code_value_10bit"] / 1023
        ours = decode_curve("clog3", np.array([code]))[0]
        reference = float(colour.models.log_decoding_CanonLog3(code))
        assert abs(ours - reference) <= 1e-6, "our decode must equal colour-science"
        assert (
            abs(ours - vector["expected"]["scene_linear_reflectance"])
            <= vendor_tolerance(vector["name"])
        ), f"colour-science disagrees with vendor doc on {vector['name']}"


def test_logc3_decode_matches_colour_science_and_vendor():
    vectors = load_vectors("logc3ei800_awg3")
    for vector in vectors["vectors"]:
        if "scene_linear_reflectance" not in vector["expected"]:
            continue
        code = vector["code_value_rgb"][0]
        ours = decode_curve("logc3", np.array([code]))[0]
        reference = float(colour.models.log_decoding_ARRILogC3(code))
        assert abs(ours - reference) <= 1e-6, "our decode must equal colour-science"
        assert (
            abs(ours - vector["expected"]["scene_linear_reflectance"])
            <= vendor_tolerance(vector["name"])
        ), f"colour-science disagrees with vendor doc on {vector['name']}"


def test_camera_gamut_rotation_is_not_bt709_identity():
    """Every camera gamut must actually rotate a saturated colour.

    The neutral vendor anchors above sit on the achromatic axis, where any gamut
    matrix is the identity, so they cannot catch a mutation that replaces the
    camera gamut with BT.709. A saturated primary does distinguish them: the true
    wide-gamut to BT.709 conversion differs materially from treating the decoded
    camera-linear as if it were already BT.709 (the identity-gamut mutation).
    """
    saturated_code = np.array([[0.62, 0.20, 0.24]])
    for name in (
        "slog3_sgamut3cine",
        "logc4_awg4",
        "vlog_vgamut",
        "clog3_cgamut",
        "logc3ei800_awg3",
    ):
        working = camera_to_working(name, saturated_code)[0]
        identity_gamut = decode_curve(_CURVE_BY_IDT[name], saturated_code)[0]
        assert float(np.max(np.abs(working - identity_gamut))) > 0.02, (
            f"{name}: gamut rotation is negligible, so a BT.709 mutation would pass"
        )


def test_idt_lut_grey_within_tolerance():
    # Through the full 65-point IDT LUT, vendor 18% grey lands at 0.18 in
    # working linear within delta E 2000 <= 0.5 (computed on resulting colors).
    for name in (
        "slog3_sgamut3cine",
        "logc4_awg4",
        "vlog_vgamut",
        "clog3_cgamut",
        "logc3ei800_awg3",
    ):
        vectors = load_vectors(name)
        grey = next(vector for vector in vectors["vectors"] if vector["name"] == "grey18")
        table = build_idt(name)
        out = apply_lut(table, np.array([grey["code_value_rgb"]], dtype=float))[0]
        want = np.array([0.18, 0.18, 0.18])
        lab_a = colour.XYZ_to_Lab(colour.RGB_to_XYZ(out, "ITU-R BT.709"))
        lab_b = colour.XYZ_to_Lab(colour.RGB_to_XYZ(want, "ITU-R BT.709"))
        delta_e = float(colour.difference.delta_E(lab_a, lab_b, method="CIE 2000"))
        assert delta_e <= 0.5, f"{name}: grey18 dE2000 {delta_e:.3f}"
