# SPDX-License-Identifier: MIT
import numpy as np
import pytest
from pathlib import Path
from colorist.lut import write_cube, read_cube, apply_lut


def identity_table(n: int) -> np.ndarray:
    ax = np.linspace(0.0, 1.0, n)
    r, g, b = np.meshgrid(ax, ax, ax, indexing="ij")
    return np.stack([r, g, b], axis=-1)


def test_cube_roundtrip(tmp_path: Path):
    t = identity_table(17)
    p = tmp_path / "id.cube"
    write_cube(p, t, "identity")
    back = read_cube(p)
    assert back.shape == (17, 17, 17, 3)
    assert np.allclose(back, t, atol=1e-6)


def test_cube_dialect(tmp_path: Path):
    p = tmp_path / "id.cube"
    write_cube(p, identity_table(17), "identity")
    text = p.read_text().splitlines()
    assert "LUT_3D_SIZE 17" in text
    assert "DOMAIN_MIN 0.0 0.0 0.0" in text
    assert "DOMAIN_MAX 1.0 1.0 1.0" in text
    # R fastest: the second data line increments R only
    data = [l for l in text if l and l[0].isdigit()]
    first = np.array(data[0].split(), dtype=float)
    second = np.array(data[1].split(), dtype=float)
    assert second[0] > first[0] and second[1] == first[1] and second[2] == first[2]


def test_apply_identity_exact_and_between_nodes():
    t = identity_table(17)
    rgb = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.5, 0.25, 0.75],
                    [0.013, 0.987, 0.5004]])
    out = apply_lut(t, rgb)
    assert np.allclose(out, rgb, atol=1e-9)


def test_apply_channel_permutation():
    # LUT that swaps R and B: table[r,g,b] = (b, g, r)
    n = 17
    t = identity_table(n)[..., ::-1].copy()
    rgb = np.array([[0.2, 0.5, 0.9]])
    out = apply_lut(t, rgb)
    assert np.allclose(out, [[0.9, 0.5, 0.2]], atol=1e-9)


def test_apply_clamps_out_of_domain():
    t = identity_table(17)
    out = apply_lut(t, np.array([[-0.5, 2.0, 0.5]]))
    assert np.allclose(out, [[0.0, 1.0, 0.5]], atol=1e-9)
