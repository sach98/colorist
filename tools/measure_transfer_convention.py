# SPDX-License-Identifier: MIT
"""Show which transfer this project encodes with, and why its files say bt709.

WHY THIS MEASUREMENT EXISTS

Two different functions are both called "Rec.709" in ordinary conversation, and
this project uses one while tagging its files with the name of the other. Review
flagged that as standards-ambiguous, correctly. The ambiguity is real and the
resolution is not obvious, so the numbers behind it are computed here rather than
asserted in prose.

  The BT.709 OETF is scene referred. It is the camera side of the system, roughly
  a 0.45 exponent with a linear toe.

  The BT.1886 EOTF is display referred. It is a plain gamma 2.4, and its inverse
  is what this project encodes with, as corrections.bt1886_encode.

They are not inverses of each other, and the gap between them is the deliberate
end-to-end system gamma for viewing camera-captured light in a dim surround.

Run:

    .venv/bin/python tools/measure_transfer_convention.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from colorist.corrections import bt1886_decode, bt1886_encode  # noqa: E402
from colorist.tools import resolve_tool  # noqa: E402


#: Scene-linear values to report. 0.18 is the conventional mid grey.
PROBES = (0.02, 0.18, 0.50, 0.90, 1.00)


def bt709_oetf(linear: np.ndarray) -> np.ndarray:
    """The BT.709 opto-electronic transfer function, scene referred."""
    linear = np.asarray(linear, dtype=np.float64)
    return np.where(linear < 0.018, 4.5 * linear, 1.099 * np.power(linear, 0.45) - 0.099)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)

    linear = np.asarray(PROBES)
    project = bt1886_encode(linear)
    oetf = bt709_oetf(linear)

    print("Encoding, and what a BT.1886 gamma 2.4 display then shows")
    print()
    print(
        f"  {'scene linear':>12} {'project code':>13} {'shown':>9}   "
        f"{'BT.709 OETF':>12} {'shown':>9}"
    )
    print(f"  {'-' * 12} {'-' * 13} {'-' * 9}   {'-' * 12} {'-' * 9}")
    for value, encoded, camera in zip(linear, project, oetf):
        print(
            f"  {value:12.5f} {encoded:13.5f} {bt1886_decode(encoded):9.5f}   "
            f"{camera:12.5f} {bt1886_decode(camera):9.5f}"
        )

    print()
    print("  The project's encode round trips exactly: what you encode is what is shown.")
    print("  The OETF path does not, and is not meant to. The difference is the")
    print("  end-to-end system gamma intended for camera light in a dim surround.")

    print()
    print("Available ffmpeg color_trc values, to show none of them means BT.1886:")
    help_text = subprocess.run(
        [resolve_tool("ffmpeg"), "-hide_banner", "-h", "full"],
        capture_output=True,
        text=True,
    ).stdout
    inside = False
    names: list[str] = []
    for line in help_text.splitlines():
        if "-color_trc" in line:
            inside = True
            continue
        if inside:
            if not line.startswith("     ") or "ED.V" not in line:
                break
            names.append(line.split()[0])
    print("  " + ", ".join(names))
    print()
    print("  There is no bt1886 option. 'bt709' is the conventional signal for")
    print("  Rec.709 SDR and is what the shipped delivery profiles declare, so the")
    print("  corpus uses it too. Read it as 'this is Rec.709 SDR', which is true,")
    print("  not as 'these samples follow the BT.709 OETF', which is false.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
