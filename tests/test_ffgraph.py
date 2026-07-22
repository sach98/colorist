# SPDX-License-Identifier: MIT
import pytest
from colorist.ffgraph import run_graph, UnexpectedNegotiation

SRC = ["-f", "lavfi", "-i", "testsrc2=size=64x64:rate=25:duration=0.2"]
NULL = ["-f", "null", "-"]


def test_banned_graph_is_detected():
    # The spec's empirical finding: eq and curves force yuv444p / rgb24.
    rep = run_graph(SRC, "format=gbrp,eq=brightness=0.01,curves=preset=lighter", NULL)
    with pytest.raises(UnexpectedNegotiation):
        rep.assert_only({"gbrp"})


def test_clean_graph_passes():
    rep = run_graph(SRC, "format=gbrpf32le,lut3d=interp=tetrahedral:file=tests/fixtures/identity17.cube", NULL)
    rep.assert_only({"gbrpf32le", "yuv420p", "yuvj420p", "rgb24"})
    # testsrc2 source emits its native format before our explicit format filter;
    # everything from the format filter onward must be gbrpf32le only:
    after = rep.formats[rep.formats.index("gbrpf32le"):]
    assert set(after) == {"gbrpf32le"}
