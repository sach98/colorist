# SPDX-License-Identifier: MIT
"""Run ffmpeg graphs and assert the negotiated pixel formats (design.md 4.3)."""
from dataclasses import dataclass
import re
import subprocess

from colorist.tools import resolve_tool

FFMPEG = resolve_tool("ffmpeg")


class UnexpectedNegotiation(AssertionError):
    pass


@dataclass
class GraphReport:
    formats: list[str]
    stderr: str

    def assert_only(self, allowed: set[str]) -> None:
        bad = [f for f in self.formats if f not in allowed]
        if bad:
            raise UnexpectedNegotiation(
                f"unexpected negotiated formats {bad}; allowed {sorted(allowed)}")


def run_graph(input_args: list[str], vf: str, output_args: list[str]) -> GraphReport:
    cmd = [FFMPEG, "-hide_banner", "-v", "verbose", *input_args, "-vf", vf, *output_args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-2000:]}")
    formats = re.findall(r"fmt:([a-z0-9]+)", proc.stderr)
    return GraphReport(formats=formats, stderr=proc.stderr)
