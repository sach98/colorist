# SPDX-License-Identifier: MIT
"""Regenerate references/corpus-manifest.yaml from corpus.catalogue().

Run this ONLY when the catalogue is deliberately changed. If a digest moves
without the catalogue changing, that is a dependency change and regenerating
would hide it, which is the one thing the manifest exists to prevent.
"""

from __future__ import annotations

from pathlib import Path
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import yaml  # noqa: E402

from colorist.corpus import manifest  # noqa: E402


HEADER = (Path(__file__).parents[1] / "references/corpus-manifest.yaml").read_text().split(
    "schema:"
)[0]


def main() -> int:
    destination = Path(__file__).parents[1] / "references/corpus-manifest.yaml"
    destination.write_text(HEADER + yaml.safe_dump(manifest(), sort_keys=False))
    print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
