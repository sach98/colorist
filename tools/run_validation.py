# SPDX-License-Identifier: MIT
"""Run the Tier A corpus through the harness and report the validation properties.

This is the first actual validation run of the evaluation harness against its own
corpus. It checks the properties from `docs/evaluation-harness.md` section 9 that
are checkable today.

WHY THE PROPERTIES ARE CHECKED ON STATISTICS AND NOT ON SCORES

Almost nothing scores. Five of the six dimensions have no target with a nameable
basis, so they report a measured value and TARGET_UNAVAILABLE. A monotonicity
check on scores would therefore be checking one dimension.

That is not a workaround, it is what property 5 asks for in the first place:
numeric agreement of the STATISTIC, not merely ordering of the score. The
statistics are exactly as measurable now as they will be once the targets are
grounded, so the ruler can be tested before it is calibrated.

WHAT IS NOT CHECKED HERE, AND WHY

- Property 2, recovery, lives in tests/test_corpus.py where the analytic inverses
  are, and needs a real encode round trip to mean anything.
- Property 4, ordering against the human scorecard, needs the Tier B clip and is
  a falsifier rather than evidence.
- Property 11, no label leakage, is a procedural rule that needs
  pre-registration, not a run.

Run:

    .venv/bin/python tools/run_validation.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from colorist.corpus import (  # noqa: E402
    ChartLayout,
    Scene,
    equal_distance_pair,
    inject,
    reference_roi,
    render,
)
from colorist.scorecard import score_delivery, skin_hue_and_chroma  # noqa: E402


TECHNICAL = {"tags_match": True, "range_legal": True, "introduced_clipping_percent": 0.0}
SEVERITIES = (0.0, 0.25, 0.5, 0.75, 1.0)
#: The dimensions each defect family is EXPECTED to move, and by how little a
#: dimension outside that set may move.
#:
#: Property 8 was first written as "a family must move its own dimension more
#: than any other". That is wrong, and the first validation run said so. Tone
#: compression reduced skin chroma by 45.98 percent while moving the black
#: placement statistic by 2.87 percent, so the naive form failed. The physics is
#: real: compressing the tonal range to 65 percent of its span pulls every colour
#: toward mid grey, which reduces colourfulness, monotonically at 13.04, 24.98,
#: 35.94 and 45.98 percent across the severity sweep. The signature has to
#: include that side effect rather than pretend defects are orthogonal.
#:
#: The naive form was also comparing percentages across incommensurable
#: quantities, an angle against a ratio against an IRE value, which is the same
#: category error this project already made once with skin hue and chroma.
#:
#: Note what tone does NOT move much: tonal_black, at 2.87 percent. The chart's
#: darkest patch sits at 24.3 IRE, so the corpus has no true black for a lift to
#: act on, and black placement is a weak detector on this content. The p99 falls
#: from 95.14 to 59.27 IRE over the same sweep and would be the strong one, but
#: it is a source-relative sub-measure and reports EVIDENCE_ABSENT without an
#: authenticated source.
#: Tone also shifts skin HUE, by 1.948 degrees at full severity, monotonically
#: at 0.477, 0.961, 1.452 and 1.948 across the sweep. That too is physics rather
#: than a bug: the tone injector is a PER-CHANNEL curve, and a per-channel curve
#: does not preserve hue. A luminance-preserving one would. This is worth
#: knowing rather than hiding, because the per-channel curves real grading
#: software offers have the same property, so a tonal defect on real footage
#: arrives with a hue shift attached.
EXPECTED_SIGNATURE = {
    "chroma": {"skin_chroma"},
    "hue": {"skin_hue"},
    "tone": {"skin_chroma", "tonal_black", "skin_hue"},
}
#: The dimension whose numeric agreement is checked per family.
PRIMARY = {"chroma": "skin_chroma", "hue": "skin_hue", "tone": "tonal_black"}
#: Relative movement below which a dimension counts as untouched.
QUIET = 0.01


def _layout() -> ChartLayout:
    return ChartLayout(rows=4, columns=6, patch_size=48, gutter=8, margin=16)


def _measure(image: np.ndarray, skin: np.ndarray, neutrals) -> dict[str, float | None]:
    card = score_delivery(
        image, skin_mask=skin, neutral_regions=neutrals, technical=TECHNICAL
    )
    return {dimension.name: dimension.value for dimension in card.dimensions}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)

    layout = _layout()
    reference = render(Scene(layout=layout))
    # Pinned once, from the reference. Section 5.3: re-deriving per image lets a
    # badly wrong skin hue drop out of its own evidence set.
    skin = reference_roi(reference, "skin")
    neutral = reference_roi(reference, "neutral")
    middle = neutral.shape[0] // 2
    top, bottom = neutral.copy(), neutral.copy()
    top[middle:] = False
    bottom[:middle] = False
    neutrals = (top, bottom)

    base = _measure(reference, skin, neutrals)
    print("Reference statistics, pinned masks, no defect")
    for name, value in base.items():
        print(f"  {name:22} {'-' if value is None else f'{value:10.5f}'}")

    print()
    print("Property 1 and 5: monotonicity and numeric agreement of the statistic")
    print()
    failures: list[str] = []
    for family, dimension in PRIMARY.items():
        readings = []
        for severity in SEVERITIES:
            damaged = inject(reference, family, severity, injector="primary")
            readings.append(_measure(damaged, skin, neutrals)[dimension])
        deltas = [abs(value - readings[0]) for value in readings]
        monotone = all(later >= earlier - 1e-9 for earlier, later in zip(deltas, deltas[1:]))
        print(f"  {family:7} -> {dimension:20} " + " ".join(f"{v:9.5f}" for v in readings))
        print(f"  {'':7}    deviation from reference " + " ".join(f"{d:9.5f}" for d in deltas))
        print(f"  {'':7}    monotonic in severity: {monotone}")
        if not monotone:
            failures.append(f"{family} is not monotonic in {dimension}")
        print()

    print("Property 8: cross-dimension specificity")
    print("  A family must move its OWN dimension and not masquerade as another.")
    print()
    watched = ("skin_hue", "skin_chroma", "tonal_black", "neutral_consistency")
    print(f"  {'family':8} " + " ".join(f"{name:>19}" for name in watched))
    for family, expected in EXPECTED_SIGNATURE.items():
        damaged = inject(reference, family, 1.0, injector="primary")
        after = _measure(damaged, skin, neutrals)
        cells, moved = [], set()
        for name in watched:
            if base[name] is None or after[name] is None:
                cells.append("-")
                continue
            scale = abs(base[name]) if abs(base[name]) > 1e-9 else 1.0
            relative = (after[name] - base[name]) / scale
            cells.append(f"{relative * 100:+18.2f}%")
            if abs(relative) > QUIET:
                moved.add(name)
        print(f"  {family:8} " + " ".join(f"{cell:>19}" for cell in cells))
        stray = moved - expected
        if stray:
            failures.append(f"{family} moved {sorted(stray)}, which is outside its signature")
        missed = {name for name in expected if name in watched} - moved
        if missed:
            failures.append(f"{family} failed to move {sorted(missed)}, which is in its signature")

    print()
    print("Property 13: equal whole-image distance, different per-dimension damage")
    print()
    first, second, severities = equal_distance_pair(reference, "chroma", "hue", 3.0)
    for label, image, severity in (("chroma", first, severities[0]), ("hue", second, severities[1])):
        after = _measure(image, skin, neutrals)
        hue_shift = after["skin_hue"] - base["skin_hue"]
        chroma_shift = (after["skin_chroma"] - base["skin_chroma"]) / base["skin_chroma"] * 100
        print(f"  {label:7} severity {severity:.4f}   skin hue {hue_shift:+7.3f} deg"
              f"   skin chroma {chroma_shift:+7.2f}%")

    print()
    print("Property 12: reference-free statistic correctness")
    print("  Every statistic above was computed from the delivery alone. The")
    print("  reference was used only to pin the masks, never to fit a transform,")
    print("  so a metric that works by estimating the residual has nothing to fit.")

    print()
    if failures:
        print(f"FAILURES: {len(failures)}")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("All checked properties hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
