# SPDX-License-Identifier: MIT
"""Tier A corpus: synthetic scenes whose correct answer is known analytically.

WHY THIS EXISTS

`docs/evaluation-harness.md` cannot validate a metric against footage whose
correct grade is a matter of opinion. This module renders scenes from published
spectral reflectance data under published illuminant spectra, so the colorimetry
of every patch is computable rather than judged, and a correction can be scored
by how close it gets to a number nobody had to agree on.

WHAT A SCENE IS

A chart of spectral reflectances, laid out spatially, lit by one illuminant or by
two split across the frame, and encoded to Rec.709 display code.

Two design choices are load-bearing and both come from review of the harness
specification:

**The layout varies.** `ChartLayout` parameterises the grid, the patch size, the
spacing, and the order patches appear in. A validation metric that locates skin
by remembering where the chart usually puts it will fail on a layout it has not
seen, which is the point: harness validation property 10 requires held-out
content and layout, not merely held-out defect severities.

**The illuminant can vary spatially.** `Scene.split_at` places a second
illuminant over part of the frame, per pixel rather than per patch, so a single
neutral patch can be lit warm on one side and cool on the other. That is the
defect that motivated v2 of this project, a white shirt reading warm on the
upper body and cool in the chest, and no global correction can undo it.

DOMAIN

Rendering produces full-range Rec.709 display-code floats in 0 to 1, encoded with
``corrections.bt1886_encode``, which is the same display encode the grading chain
ends with and the same domain ``measure`` treats as canonical. Scene XYZ is
normalised so a perfect diffuser under the scene's reference illuminant has
``Y = 1``.

THE TRANSFER, AND WHY THE FILES SAY bt709 WHEN THE PIXELS ARE GAMMA 2.4

Review flagged this as standards-ambiguous. It is worth stating precisely because
the two transfers involved are genuinely different and both are called "Rec.709"
in casual use.

These values are **display referred**. They are encoded with the inverse of the
BT.1886 EOTF, a plain gamma 2.4, so a code value is what a BT.1886 display shows.
Measured on this machine::

    scene linear 0.18 -> gamma 2.4 inverse -> 0.48944 -> BT.1886 display -> 0.18000

The BT.709 OETF is a different function for a different job: it is scene
referred, the camera side of the system, and it is NOT the inverse of BT.1886::

    scene linear 0.18 -> BT.709 OETF -> 0.40901 -> BT.1886 display -> 0.11699

That second line is not a bug either. The gap between the BT.709 OETF and the
BT.1886 EOTF is the deliberate end-to-end system gamma for viewing
camera-captured light in a dim surround. It is simply not what a display-referred
deliverable wants, and a deliverable is what this corpus produces.

So the encode is right. The TAG is a separate problem: ffmpeg's ``color_trc``
vocabulary has no value meaning BT.1886. The options are bt709, gamma22,
gamma28, smpte170m, iec61966-2-1 and similar, and none of them says gamma 2.4 for
SDR video. ``bt709`` is the conventional signalling for Rec.709 SDR and is what
the project's shipped delivery profiles already declare, so the corpus matches
them rather than inventing a different convention.

Read the tag as "this is Rec.709 SDR", which is true, and not as "these samples
follow the BT.709 OETF", which is false. The limitation is in the tagging
vocabulary, not in the pixels. ``tools/measure_transfer_convention.py``
reproduces every number above.

WHAT IS NOT MODELLED

No camera spectral sensitivities, no lens, no noise, no compression. A scene is
colorimetry, not photography. Encoding to a real container is a separate step so
that codec effects can be measured rather than assumed, which harness validation
property 7 needs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import subprocess
from typing import Final

import numpy as np

from colorist.corrections import bt1886_encode


try:  # pragma: no cover - exercised only without the dependency installed
    import colour
except ModuleNotFoundError:  # pragma: no cover
    colour = None  # type: ignore[assignment]


OBSERVER: Final[str] = "CIE 1931 2 Degree Standard Observer"
#: The scene is encoded through the Rec.709 primaries with this white point. A
#: scene lit by anything else and NOT adapted to it carries a cast, which is
#: exactly defect family D1.
ENCODE_WHITE: Final[str] = "D65"


#: The mid-neutral patch each supported chart uses for the scene surround.
#: Charts name their greys differently, so this cannot be one string. A chart
#: absent from this mapping is usable, but its caller has to name the surround,
#: because silently picking one would mean guessing which patch is neutral.
DEFAULT_SURROUND: Final[dict[str, str]] = {
    "ISO 17321-1": "neutral 5 (.70 D)",
    "BabelColor Average": "neutral 5 (.70 D)",
    "cc_ohta": "neutral 5 (.70 D)",
    "ColorChecker N Ohta": "neutral 5 (.70 D)",
    "PMC": "Gray-50",
}


class CorpusError(ValueError):
    """Raised when a scene cannot be rendered as specified."""


@dataclass(frozen=True)
class ChartLayout:
    """Where each patch sits in the frame.

    ``order`` is a permutation of patch indices. Position ``i`` of the grid shows
    the chart's patch number ``order[i]``, so two layouts can place the same
    reflectance in different places. A metric that has memorised "skin is the
    top-left patch" is wrong on any layout whose order differs.
    """

    rows: int
    columns: int
    patch_size: int = 48
    gutter: int = 8
    margin: int = 16
    order: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.rows < 1 or self.columns < 1:
            raise CorpusError("layout needs at least one row and one column")
        if self.patch_size < 2:
            raise CorpusError("patch_size must be at least 2 pixels")
        if self.gutter < 0 or self.margin < 0:
            raise CorpusError("gutter and margin must not be negative")
        cells = self.rows * self.columns
        if self.order and sorted(self.order) != list(range(cells)):
            raise CorpusError(
                f"order must be a permutation of 0..{cells - 1}, got {self.order}"
            )

    @property
    def cells(self) -> int:
        return self.rows * self.columns

    @property
    def placement(self) -> tuple[int, ...]:
        """The permutation actually used, defaulting to identity."""
        return self.order or tuple(range(self.cells))

    def resolution(self) -> tuple[int, int]:
        """Return ``(width, height)`` in pixels.

        Both are forced even because the delivery profiles this project ships
        encode 4:2:0, which cannot represent an odd dimension.
        """
        width = 2 * self.margin + self.columns * self.patch_size + (self.columns - 1) * self.gutter
        height = 2 * self.margin + self.rows * self.patch_size + (self.rows - 1) * self.gutter
        return width + width % 2, height + height % 2

    def rect(self, cell: int) -> tuple[int, int, int, int]:
        """Return ``(x0, y0, x1, y1)`` for one grid cell, right and lower exclusive."""
        if not 0 <= cell < self.cells:
            raise CorpusError(f"cell {cell} is outside a {self.rows}x{self.columns} layout")
        row, column = divmod(cell, self.columns)
        x0 = self.margin + column * (self.patch_size + self.gutter)
        y0 = self.margin + row * (self.patch_size + self.gutter)
        return x0, y0, x0 + self.patch_size, y0 + self.patch_size

    def rect_for_patch(self, patch_index: int) -> tuple[int, int, int, int]:
        """Return the rectangle showing chart patch ``patch_index``."""
        placement = self.placement
        try:
            cell = placement.index(patch_index)
        except ValueError as error:
            raise CorpusError(f"patch {patch_index} is not placed by this layout") from error
        return self.rect(cell)


@dataclass(frozen=True)
class Scene:
    """A chart lit by one illuminant, or by two split across the frame.

    ``balanced_for`` names the illuminant the CAMERA was set to. It is one
    setting for the whole frame, never per region, and leaving it at the encode
    white while the scene is lit by something else is what produces a cast.

    ``split_at`` is a fraction of frame width. Left of it the scene is lit by
    ``illuminant``; right of it by ``second_illuminant``. The boundary is applied
    per pixel, so a patch straddling it is lit both ways, which is the whole
    point of the family it serves.
    """

    chart: str = "ISO 17321-1"
    layout: ChartLayout = field(default_factory=lambda: ChartLayout(rows=4, columns=6))
    illuminant: str = "D65"
    second_illuminant: str | None = None
    split_at: float | None = None
    balanced_for: str = ENCODE_WHITE
    exposure: float = 1.0
    surround: str | None = None

    @property
    def surround_patch(self) -> str:
        """The patch used for the scene surround, defaulted per chart."""
        if self.surround is not None:
            return self.surround
        try:
            return DEFAULT_SURROUND[self.chart]
        except KeyError as error:
            raise CorpusError(
                f"chart {self.chart!r} has no default surround patch; name one "
                f"explicitly. Known defaults: {sorted(DEFAULT_SURROUND)}"
            ) from error

    def __post_init__(self) -> None:
        if (self.second_illuminant is None) != (self.split_at is None):
            raise CorpusError(
                "a split scene needs both second_illuminant and split_at, or neither"
            )
        if self.split_at is not None and not 0.0 < self.split_at < 1.0:
            raise CorpusError("split_at must lie strictly between 0 and 1")


def _require_colour() -> None:
    if colour is None:  # pragma: no cover
        raise CorpusError("corpus rendering requires the colour-science dependency")


@lru_cache(maxsize=None)
def _aligned(kind: str, chart_or_none: str | None, name: str):
    """Return one spectral distribution resampled onto the observer's shape.

    Reflectance data, illuminant spectra, and the colour matching functions are
    published on different wavelength ranges and intervals. Something has to
    interpolate them onto a common shape before they can be integrated, and left
    alone colour-science does it implicitly and warns each time.

    Doing it here makes the resampling an explicit, stated step: every spectrum
    is aligned to the CIE 1931 2 degree observer's own shape, which is the
    common denominator the integration is defined on. The results are identical
    to the implicit path; what changes is that the choice is visible and is made
    once rather than per call.
    """
    _require_colour()
    shape = colour.MSDS_CMFS[OBSERVER].shape
    if kind == "illuminant":
        try:
            spectrum = colour.SDS_ILLUMINANTS[name]
        except KeyError as error:
            raise CorpusError(f"unknown illuminant {name!r}") from error
    else:
        try:
            spectrum = colour.SDS_COLOURCHECKERS[chart_or_none][name]
        except KeyError as error:
            raise CorpusError(
                f"unknown patch {name!r} in chart {chart_or_none!r}"
            ) from error
    return spectrum.copy().align(shape)


@lru_cache(maxsize=None)
def _perfect_diffuser_xyz(illuminant: str) -> tuple[float, float, float]:
    """XYZ of a perfect diffuser under this illuminant, unnormalised."""
    _require_colour()
    spectrum = _aligned("illuminant", None, illuminant)
    white = colour.sd_to_XYZ(
        colour.colorimetry.sd_ones(spectrum.shape),
        colour.MSDS_CMFS[OBSERVER],
        spectrum,
    )
    return tuple(float(component) for component in white)  # type: ignore[return-value]


def _patch_names(chart: str) -> list[str]:
    _require_colour()
    try:
        return list(colour.SDS_COLOURCHECKERS[chart].keys())
    except KeyError as error:
        raise CorpusError(f"unknown chart {chart!r}") from error


def _white_xyz(illuminant: str) -> np.ndarray:
    """XYZ of a perfect diffuser under this illuminant, normalised to Y = 1."""
    white = np.asarray(_perfect_diffuser_xyz(illuminant), dtype=np.float64)
    return white / white[1]


def patch_display_rgb(
    chart: str,
    patch: str,
    illuminant: str,
    balanced_for: str = ENCODE_WHITE,
    exposure: float = 1.0,
) -> np.ndarray:
    """Return one patch's Rec.709 display-code RGB, the analytic ground truth.

    ``illuminant`` is the light actually falling on the patch. ``balanced_for``
    is the illuminant the CAMERA was set to, which is a property of the camera
    and not of the pixel.

    THAT DISTINCTION IS THE WHOLE POINT, and an earlier version got it wrong in a
    way that quietly destroyed the corpus's most important defect family.

    The earlier code adapted from each pixel's OWN illuminant to a destination
    white. On a single-illuminant scene that is indistinguishable from a correct
    camera balance, so it looked right. On a SPLIT scene it is a per-region
    correction: the tungsten side received a tungsten-to-daylight adaptation while
    the daylight side received an identity, so the mixed-lighting defect was
    corrected by the generator before any tool saw it. Measured on the chart's
    neutral patch, the warm-to-cool split across the boundary collapsed from 97.6
    of an 8 bit code value to 0.256.

    A real camera has ONE white balance setting applied to the entire frame. So
    the adaptation here is a single transform from the balanced-for white to the
    encode white, applied uniformly, and a pixel lit by something else keeps the
    cast that mismatch produces. That is what a mixed-lighting defect IS.
    """
    return bt1886_encode(
        np.clip(patch_linear_rgb(chart, patch, illuminant, balanced_for, exposure), 0.0, 1.0)
    )


def patch_linear_rgb(
    chart: str,
    patch: str,
    illuminant: str,
    balanced_for: str = ENCODE_WHITE,
    exposure: float = 1.0,
) -> np.ndarray:
    """The same value BEFORE the clip to the Rec.709 cube.

    This exists so that what clipping destroys is visible rather than implicit.
    ``patch_display_rgb`` clips, which is right because a delivery cannot carry
    out-of-gamut values, but it means the corpus loses information and a caller
    otherwise cannot tell which patches lost it.
    """
    _require_colour()
    spectrum = _aligned("illuminant", None, illuminant)
    reflectance = _aligned("reflectance", chart, patch)
    white_y = _perfect_diffuser_xyz(illuminant)[1]
    xyz = colour.sd_to_XYZ(reflectance, colour.MSDS_CMFS[OBSERVER], spectrum) / white_y

    if balanced_for != ENCODE_WHITE:
        xyz = colour.chromatic_adaptation(
            xyz,
            _white_xyz(balanced_for),
            _white_xyz(ENCODE_WHITE),
            method="Von Kries",
            transform="CAT02",
        )

    linear = colour.XYZ_to_RGB(
        xyz,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_encoding=False,
        chromatic_adaptation_transform=None,
    )
    return linear * exposure


def clipping_report(scene: Scene) -> dict[str, dict[str, float | bool]]:
    """Per patch, how far outside the Rec.709 cube it falls before clipping.

    WHY THIS IS PART OF THE CORPUS CONTRACT AND NOT AN IMPLEMENTATION DETAIL

    Harness validation property 2 requires that applying a defect's analytic
    inverse returns the score to the reference ceiling. Clipping breaks that for
    any patch it touches: the information is gone before the file is written and
    no inverse recovers it. A corpus that clipped quietly and then claimed exact
    recoverability would be asserting something false.

    Two measured facts on the ISO 17321-1 chart make this a thing to report
    rather than a bug to fix:

    - **The reference scene itself clips.** Under D65 with a D65 balance, the
      cyan patch sits at linear R = -0.0334. It is outside the Rec.709 gamut as a
      matter of colorimetry, with no defect involved. So "clipping only affects
      damaged items" is false.
    - **Negative excursions cannot be fixed by exposure.** Every scene measured
      has at least one patch below zero, from -0.0105 to -0.0485. Exposure moves
      the top of the range, not the bottom. Under illuminant A on a daylight
      balance six of 24 patches clip, and a gain of 0.6098 would be needed to fit
      the top while cyan would still be negative.

    So the honest response is neither "avoid clipping" nor "ignore it" but
    "report it". A consumer testing recovery excludes the patches this scene
    destroyed information for, and says how many it excluded.
    """
    names = _patch_names(scene.chart)
    illuminants = [scene.illuminant]
    if scene.second_illuminant is not None:
        illuminants.append(scene.second_illuminant)

    report: dict[str, dict[str, float | bool]] = {}
    for name in names:
        lows, highs = [], []
        for illuminant in illuminants:
            linear = patch_linear_rgb(
                scene.chart, name, illuminant, scene.balanced_for, scene.exposure
            )
            lows.append(float(linear.min()))
            highs.append(float(linear.max()))
        low, high = min(lows), max(highs)
        report[name] = {
            "linear_min": low,
            "linear_max": high,
            "clipped_low": low < 0.0,
            "clipped_high": high > 1.0,
            "clipped": low < 0.0 or high > 1.0,
        }
    return report


def recoverable_patches(reference: Scene, defect: Scene) -> tuple[str, ...]:
    """Patches whose information survives BOTH scenes, so recovery is testable.

    A patch clipped in the defect but not the reference has lost information no
    inverse restores. A patch clipped in both is equally unrecoverable. Only
    patches clipped in neither can be held to the exact-recovery standard of
    validation property 2, and the count of exclusions belongs in the report.
    """
    before = clipping_report(reference)
    after = clipping_report(defect)
    return tuple(
        name
        for name in before
        if not before[name]["clipped"] and not after.get(name, {}).get("clipped", True)
    )


def expected_patches(scene: Scene) -> dict[str, np.ndarray]:
    """Ground-truth display RGB per patch name, for a scene with one illuminant.

    A split scene has no single answer per patch, because a straddling patch is
    two colours. Callers wanting per-region truth on a split scene use
    ``expected_patches`` on each side's equivalent single-illuminant scene.
    """
    if scene.split_at is not None:
        raise CorpusError(
            "a split scene has no single expected value per patch; ask per side"
        )
    return {
        name: patch_display_rgb(
            scene.chart, name, scene.illuminant, scene.balanced_for, scene.exposure
        )
        for name in _patch_names(scene.chart)
    }


def patch_map(scene: Scene) -> np.ndarray:
    """Return an (h, w) array naming which chart patch each pixel shows.

    The surround is a real chart reflectance rather than a made-up grey, so it
    responds to the illuminant like everything else. That matters for a split
    scene: a synthetic constant surround would leave the lighting boundary
    visible only on patches, and a metric could then find the boundary by
    looking for where the patches disagree with a background that never changes.
    """
    names = _patch_names(scene.chart)
    layout = scene.layout
    if layout.cells > len(names):
        raise CorpusError(
            f"layout has {layout.cells} cells but chart {scene.chart!r} has "
            f"{len(names)} patches"
        )
    surround = scene.surround_patch
    if surround not in names:
        raise CorpusError(
            f"surround patch {surround!r} is not in chart {scene.chart!r}"
        )

    width, height = layout.resolution()
    indices = np.full((height, width), names.index(surround), dtype=np.int32)
    for cell, patch_index in enumerate(layout.placement):
        x0, y0, x1, y1 = layout.rect(cell)
        indices[y0:y1, x0:x1] = patch_index
    return indices


def split_through_cell(layout: ChartLayout, cell: int, across: float = 0.5) -> float:
    """Return the ``split_at`` fraction that cuts one grid cell.

    Whether a lighting boundary falls inside a patch or lands in a gutter is an
    accident of the layout arithmetic, and the mixed-lighting family is only
    meaningful when it falls inside one: the defect being modelled is a single
    object lit two ways, not two objects lit differently. This computes a split
    that is guaranteed to bisect the named cell, so a corpus item can require the
    case rather than hope for it.

    ``across`` is where within the cell to cut, from 0 at its left edge to 1 at
    its right.
    """
    if not 0.0 < across < 1.0:
        raise CorpusError("across must lie strictly between 0 and 1")
    x0, _, x1, _ = layout.rect(cell)
    width, _ = layout.resolution()
    boundary = x0 + across * (x1 - x0)
    fraction = boundary / width
    if not 0.0 < fraction < 1.0:  # pragma: no cover - layout guarantees interior cells
        raise CorpusError(f"cell {cell} cannot be split within the frame")
    return fraction


def illuminant_map(scene: Scene) -> np.ndarray:
    """Return an (h, w) boolean: True where the second illuminant lights the scene."""
    width, height = scene.layout.resolution()
    side = np.zeros((height, width), dtype=bool)
    if scene.split_at is not None:
        side[:, int(round(scene.split_at * width)) :] = True
    return side


def render(scene: Scene) -> np.ndarray:
    """Render a scene to full-range Rec.709 display-code floats, shape (h, w, 3)."""
    names = _patch_names(scene.chart)
    indices = patch_map(scene)
    side = illuminant_map(scene)

    lit = [scene.illuminant]
    if scene.second_illuminant is not None:
        lit.append(scene.second_illuminant)

    # One lookup table per illuminant, indexed by patch number, so the render is
    # a gather rather than a loop over rectangles. That also makes a straddling
    # patch fall out for free instead of needing its own case.
    tables = [
        np.stack(
            [
                patch_display_rgb(
                    scene.chart, name, illuminant, scene.balanced_for, scene.exposure
                )
                for name in names
            ]
        )
        for illuminant in lit
    ]

    image = tables[0][indices]
    if len(tables) > 1:
        image[side] = tables[1][indices[side]]
    return image


# ---------------------------------------------------------------------------
# Defect injection.
#
# Families D1 and D2 of the harness specification are properties of a Scene: a
# non-D65 illuminant, and a spatially split one. They need no injector because
# the defect IS the lighting.
#
# Families D3, D4, and D5 are transforms applied to a rendered reference, and
# for those the correct answer is the reference itself.
#
# TWO INJECTORS, ON PURPOSE
#
# Harness validation property 10 requires held-out defect IMPLEMENTATIONS, not
# just held-out severities. A metric that has learned one injector's arithmetic
# can interpolate any severity of it while understanding nothing. So each family
# has two independent implementations that work in different colour spaces and
# therefore produce different pixels for the same nominal severity:
#
#   "primary"    works in the domains this project itself uses, the log grading
#                space from corrections.shaper and Oklab.
#   "secondary"  works in display code and CIELAB, chosen because they are
#                unrelated to the primary's domains rather than because they are
#                better.
#
# Neither is the "right" one. Agreement between them is not expected and is not
# the point. What matters is that a metric validated on one is then tested on the
# other, and a metric that only knows the first will fail.
#
# HOW INDEPENDENT THEY ACTUALLY ARE, MEASURED RATHER THAN CLAIMED
#
# Not fully. Review measured that fitting only the primary injector's severity
# reproduced the secondary injector's tone and chroma defects with a residual RMS
# of roughly 8 to 17 percent of the defect RMS. They remain closely related
# one-dimensional transform families: the two polar injectors share the severity
# formula, the radius-and-angle operation, and the RGB to XYZ path, differing only
# in the opponent space. A metric that has learned one will not sail through the
# other unchanged, but it is not starting from nothing either.
#
# Treat this as one axis of held-out variation among several, not as a guarantee.
# The stronger axes are held-out CONTENT (a different chart, a different layout)
# and, still missing, content that is not a chart at all.
#
# WHAT THE INJECTORS MAY NOT SHARE, AND WHAT THEY MAY
#
# May NOT: correction algebra. The primary tone injector used to call
# corrections.shaper, and that was a real violation of the specification's rule
# that an injected defect and the code correcting it must not share an
# implementation, because v2's correction is expected to work in that same curve.
# It now uses its own log curve, owing nothing to the grading chain.
#
# MAY: the display transfer, bt1886_encode and bt1886_decode. Those define what a
# display code value MEANS. The corpus and the tool have to agree on that or they
# are measuring different quantities, and a disagreement there would be a bug in
# the corpus rather than an independence property worth having.
# ---------------------------------------------------------------------------

#: Chroma scale at severity 1.0. Below 1 because the motivating defect was skin
#: chroma measured at roughly half its natural value.
CHROMA_SCALE_AT_FULL: Final[float] = 0.5
#: Hue rotation in degrees at severity 1.0.
HUE_ROTATION_AT_FULL: Final[float] = 12.0
#: Black lift and highlight crush, as a fraction of range, at severity 1.0.
TONE_LIFT_AT_FULL: Final[float] = 0.10
TONE_CRUSH_AT_FULL: Final[float] = 0.25
#: Pedestal of the primary tone injector's own log curve. Chosen so the curve is
#: finite at scene-linear zero and has no relationship to the grading shaper.
TONE_LOG_PEDESTAL: Final[float] = 0.01

FAMILIES: Final[tuple[str, ...]] = ("tone", "chroma", "hue")
INJECTORS: Final[tuple[str, ...]] = ("primary", "secondary")


def _display_to_linear_rgb(display: np.ndarray) -> np.ndarray:
    from colorist.corrections import bt1886_decode

    return bt1886_decode(display)


def _display_to_xyz(display: np.ndarray) -> np.ndarray:
    _require_colour()
    return colour.RGB_to_XYZ(
        _display_to_linear_rgb(display),
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_decoding=False,
        chromatic_adaptation_transform=None,
    )


def _xyz_to_display(xyz: np.ndarray) -> np.ndarray:
    _require_colour()
    linear = colour.XYZ_to_RGB(
        xyz,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_encoding=False,
        chromatic_adaptation_transform=None,
    )
    return bt1886_encode(np.clip(linear, 0.0, 1.0))


def _scale_polar(values: np.ndarray, scale: float, rotate_degrees: float) -> np.ndarray:
    """Scale radius and rotate angle of the last-axis opponent pair in place-safe form."""
    a, b = values[..., 1], values[..., 2]
    radius = np.hypot(a, b) * scale
    angle = np.arctan2(b, a) + np.radians(rotate_degrees)
    out = values.copy()
    out[..., 1] = radius * np.cos(angle)
    out[..., 2] = radius * np.sin(angle)
    return out


def inject(
    image: np.ndarray, family: str, severity: float, *, injector: str = "primary"
) -> np.ndarray:
    """Apply a known defect to a rendered reference and return the damaged image.

    ``severity`` runs from 0, which is the identity, to 1, which is the amount
    named by the module constants. The correct answer for any injected image is
    the reference it was made from.
    """
    if family not in FAMILIES:
        raise CorpusError(f"unknown defect family {family!r}, expected one of {FAMILIES}")
    if injector not in INJECTORS:
        raise CorpusError(f"unknown injector {injector!r}, expected one of {INJECTORS}")
    if not 0.0 <= severity <= 1.0:
        raise CorpusError("severity must lie between 0 and 1 inclusive")

    display = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    if severity == 0.0:
        return display

    if family == "tone":
        return _inject_tone(display, severity, injector)
    scale = 1.0 + severity * (CHROMA_SCALE_AT_FULL - 1.0) if family == "chroma" else 1.0
    rotation = severity * HUE_ROTATION_AT_FULL if family == "hue" else 0.0
    return _inject_polar(display, scale, rotation, injector)


def _inject_tone(display: np.ndarray, severity: float, injector: str) -> np.ndarray:
    """Lift black and crush highlights by a known amount.

    This reproduces the shape of the motivating clip's tonal defect: a delivery
    whose black never reached zero and whose highlights never reached white.
    """
    lift = severity * TONE_LIFT_AT_FULL
    ceiling = 1.0 - severity * TONE_CRUSH_AT_FULL

    if injector == "secondary":
        # Straight linear remap of the display-code range.
        return lift + display * (ceiling - lift)

    # A self-contained log remap. This deliberately does NOT call
    # corrections.shaper, which an earlier version did.
    #
    # The specification requires that an injected defect and the code that
    # corrects it not share an implementation, because a shared error cancels and
    # the recovery test then passes while measuring nothing. Importing the
    # production grading curve here broke that rule directly: v2's correction
    # algebra is expected to work in that same curve.
    #
    # So the curve below is written for this module and owes nothing to the
    # grading chain. It is an ordinary log encode with a small pedestal, chosen
    # because it is simple enough to be obviously independent, not because it is
    # a good grading curve.
    linear = _display_to_linear_rgb(display)
    encoded = np.log2(linear + TONE_LOG_PEDESTAL) - np.log2(TONE_LOG_PEDESTAL)
    encoded /= np.log2(1.0 + TONE_LOG_PEDESTAL) - np.log2(TONE_LOG_PEDESTAL)
    compressed = lift + encoded * (ceiling - lift)
    span = np.log2(1.0 + TONE_LOG_PEDESTAL) - np.log2(TONE_LOG_PEDESTAL)
    decoded = np.exp2(compressed * span + np.log2(TONE_LOG_PEDESTAL)) - TONE_LOG_PEDESTAL
    return bt1886_encode(np.clip(decoded, 0.0, 1.0))


def _inject_polar(
    display: np.ndarray, scale: float, rotation: float, injector: str
) -> np.ndarray:
    """Scale chroma and rotate hue in Oklab (primary) or CIELAB (secondary)."""
    _require_colour()
    xyz = _display_to_xyz(display)
    if injector == "secondary":
        lab = colour.XYZ_to_Lab(
            xyz, illuminant=colour.RGB_COLOURSPACES["ITU-R BT.709"].whitepoint
        )
        return _xyz_to_display(
            colour.Lab_to_XYZ(
                _scale_polar(lab, scale, rotation),
                illuminant=colour.RGB_COLOURSPACES["ITU-R BT.709"].whitepoint,
            )
        )
    oklab = colour.XYZ_to_Oklab(xyz)
    return _xyz_to_display(colour.Oklab_to_XYZ(_scale_polar(oklab, scale, rotation)))


# ---------------------------------------------------------------------------
# Encoding a scene to a file the rest of the tool can actually read.
#
# A rendered scene is a float array. The harness has to measure a DELIVERY, so
# the corpus writes real video through the real encoder, and the difference
# between what was rendered and what comes back out is the pipeline's own noise
# floor. That floor is not an annoyance to be hidden: harness validation
# property 7 requires the score to survive a codec re-encode, and a required
# tolerance that is not measured is a guess.
# ---------------------------------------------------------------------------

#: Frames written per corpus item. Three is the minimum for the sampler in
#: measure.sample_positions to have distinct 25, 50, and 75 percent positions,
#: and the shot-length guard in measure_shot treats anything under three as
#: insufficient temporal coverage.
CORPUS_FRAMES: Final[int] = 5
CORPUS_FPS: Final[int] = 25

#: Code value that means display white when writing a full-range 16 bit payload.
#:
#: NOT 65535, and getting this wrong silently corrupts every ground truth in the
#: corpus. ffmpeg's full-range 16 bit YUV carries the 8 bit full-range convention
#: into 16 bits by shifting left 8, so its peak is 255 << 8 = 65280. Writing
#: 65535 as white overshoots by exactly 65535 / 65280 = 1.00390625, and the
#: round trip then comes back with a gain rather than an error, which is the
#: dangerous kind of wrong: it looks like a clean image, just not the one that
#: was rendered.
#:
#: Measured on this machine, ffmpeg 8.1.2, rendering a 24 patch chart and
#: decoding it back through render.read_frame_rgb:
#:
#:     peak 65535 -> yuv444p16le   gain 1.003888, worst error 0.957 of an 8 bit code
#:     peak 65280 -> yuv444p16le   gain 0.999975, worst error 0.019 of an 8 bit code
#:
#: The second line is the corpus noise floor and it is what the round-trip test
#: asserts against.
FULL_RANGE_16BIT_PEAK: Final[int] = 255 << 8


def write_scene(
    image: np.ndarray,
    destination: Path,
    *,
    frames: int = CORPUS_FRAMES,
    fps: int = CORPUS_FPS,
) -> Path:
    """Write a still as a lossless full-range BT.709 video, tagged correctly.

    FFV1 in Matroska, full-range 4:4:4 at 16 bits, tagged BT.709 throughout.

    Three choices, each for a reason:

    - **Lossless**, so the analytic ground truth survives to the file. A lossy
      carrier would mean every corpus expectation carried an unmeasured error.
    - **4:4:4, not 4:2:0**, so no chroma subsampling. The corpus is used to
      validate a measurement instrument; subsampling belongs in the delivery
      encode being tested, not in the reference the test is judged against.
    - **YCbCr, not RGB**, because an RGB file has no colour matrix and ffmpeg
      tags it `gbr`. That is honest for RGB but it is not the shape of a
      delivery, and the tool under test reads deliveries. Writing YCbCr means the
      carrier goes through the same matrix conversion a real file does.

    Encoding through a lossy delivery profile is a separate step, because mixing
    the two would make it impossible to say whether an error came from the grade
    or from the codec.
    """
    from colorist.tools import resolve_tool

    if frames < 1:
        raise CorpusError("a corpus item needs at least one frame")
    array = np.asarray(image, dtype=np.float64)
    if array.ndim != 3 or array.shape[-1] != 3:
        raise CorpusError("scene image must be shaped (height, width, 3)")
    height, width = array.shape[:2]
    if width % 2 or height % 2:
        raise CorpusError(f"scene is {width}x{height}; both dimensions must be even")

    quantised = np.rint(np.clip(array, 0.0, 1.0) * FULL_RANGE_16BIT_PEAK).astype("<u2")
    payload = quantised.tobytes() * frames

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            resolve_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb48le",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
            "-frames:v", str(frames),
            "-vf", "scale=in_range=pc:out_range=pc:out_color_matrix=bt709,format=yuv444p16le",
            "-c:v", "ffv1",
            "-color_range", "pc", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-f", "matroska", str(destination),
        ],
        input=payload,
        capture_output=True,
    )
    if result.returncode != 0:
        raise CorpusError(
            f"corpus encode failed: {result.stderr.decode('utf-8', 'replace')[-2000:]}"
        )
    return destination


# ---------------------------------------------------------------------------
# Analytic inverses.
#
# Harness validation property 2 requires that applying a defect's analytic
# inverse returns the score to the reference ceiling. These are those inverses.
#
# WHAT PROPERTY 2 ACTUALLY TESTS, AND A TRAP IN IT
#
# An exact inverse applied to the pre-encode float is a weak test and worth being
# honest about: inject then invert is the identity by construction, so the
# "restored" image IS the reference and the metric is only being asked whether it
# gives identical images identical scores. If the injector and the inverse shared
# a bug, it would cancel and the test would still pass while proving nothing.
#
# The test becomes meaningful when the inverse is applied to the DELIVERED image,
# after encoding, quantisation, clipping, and any codec. Then inject, encode,
# decode, invert is NOT the identity, and the question becomes whether the metric
# returns near the reference ceiling despite everything the pipeline did. That is
# the intended use of these functions.
#
# Note the separate rule these do not violate. The specification forbids the
# INJECTOR and the production CORRECTION code sharing an implementation, because
# there a shared error really would cancel and hide a broken correction. An
# analytic inverse is not correction code and is not a candidate for shipping; it
# exists only to restore a known transform inside a test.
# ---------------------------------------------------------------------------


def invert(
    image: np.ndarray, family: str, severity: float, *, injector: str = "primary"
) -> np.ndarray:
    """Undo ``inject`` for the same family, severity, and injector.

    Applied to a pre-encode float this is the exact identity. Applied to a
    delivered image it is the analytic inverse acting on whatever the pipeline
    delivered, which is the case validation property 2 cares about.
    """
    if family not in FAMILIES:
        raise CorpusError(f"unknown defect family {family!r}, expected one of {FAMILIES}")
    if injector not in INJECTORS:
        raise CorpusError(f"unknown injector {injector!r}, expected one of {INJECTORS}")
    if not 0.0 <= severity <= 1.0:
        raise CorpusError("severity must lie between 0 and 1 inclusive")

    display = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    if severity == 0.0:
        return display

    if family == "tone":
        return _invert_tone(display, severity, injector)
    scale = 1.0 + severity * (CHROMA_SCALE_AT_FULL - 1.0) if family == "chroma" else 1.0
    rotation = severity * HUE_ROTATION_AT_FULL if family == "hue" else 0.0
    return _inject_polar(display, 1.0 / scale, -rotation, injector)


def _invert_tone(display: np.ndarray, severity: float, injector: str) -> np.ndarray:
    """Undo the range compression, in whichever domain applied it."""
    lift = severity * TONE_LIFT_AT_FULL
    ceiling = 1.0 - severity * TONE_CRUSH_AT_FULL
    span = ceiling - lift

    if injector == "secondary":
        return np.clip((display - lift) / span, 0.0, 1.0)

    linear = _display_to_linear_rgb(display)
    log_span = np.log2(1.0 + TONE_LOG_PEDESTAL) - np.log2(TONE_LOG_PEDESTAL)
    encoded = (
        np.log2(linear + TONE_LOG_PEDESTAL) - np.log2(TONE_LOG_PEDESTAL)
    ) / log_span
    expanded = (encoded - lift) / span
    decoded = (
        np.exp2(expanded * log_span + np.log2(TONE_LOG_PEDESTAL)) - TONE_LOG_PEDESTAL
    )
    return bt1886_encode(np.clip(decoded, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Pinned regions of interest.
#
# WHY A NULL CASE CANNOT BE STATED WITHOUT THIS
#
# Harness validation property 7 asks that the score not move under changes that
# are not grading defects. The natural way to check that is to compute a
# statistic on both members of a pair and compare. On a masked statistic that
# does not work, and the reason is not obvious enough to leave implicit.
#
# ``measure._skin_mask`` gates on absolute HSV value between 0.25 and 0.95, and
# ``measure._neutral_mask`` on absolute luma between 0.25 and 0.90. So a change
# in exposure moves regions ACROSS those thresholds, and the statistic is then a
# median over a different population. No per-pixel invariance law survives that,
# however well behaved the pixels are.
#
# Measured on the ISO 17321-1 chart under D65, deriving the mask per image:
#
#     exposure   skin mask px   skin saturation median
#         1.000            512                 0.362748
#         0.250            512                 0.362748
#         0.125            256                 0.318672
#
# The dark skin patch crosses SKIN_VALUE_MIN and leaves. Neutral is worse: under
# illuminant A the statistic is not even monotonic, reading 14.03 code values at
# full exposure, 11.19 at half and 17.67 at a quarter, RISING as the image gets
# darker because a different set of patches passes the gates, and at an eighth
# the mask is empty and the dimension is absent evidence.
#
# Four of the six scorecard dimensions are masked statistics, so all four inherit
# this. The fix is to derive the region ONCE and apply it to both members of the
# pair, which is what the frozen-ROI machinery in verify.py exists for. This is
# the corpus-side helper for the same idea.
# ---------------------------------------------------------------------------

ROI_KINDS: Final[tuple[str, ...]] = ("skin", "neutral")


def reference_roi(image: np.ndarray, kind: str) -> np.ndarray:
    """Derive an ROI mask ONCE, from the reference member of a pair.

    Pass the resulting mask to every other member. Deriving it per image is what
    makes an invariance property untestable, because the mask then moves with the
    thing being tested.
    """
    from colorist.measure import _neutral_mask, _skin_mask

    if kind not in ROI_KINDS:
        raise CorpusError(f"unknown ROI kind {kind!r}, expected one of {ROI_KINDS}")
    selector = _skin_mask if kind == "skin" else _neutral_mask
    return selector(np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0))


def masked_statistic(image: np.ndarray, mask: np.ndarray, statistic: str) -> float:
    """Compute one scorecard-style statistic through a SUPPLIED mask.

    Returns NaN when the mask selects nothing, rather than a number. An empty
    region is absent evidence and must not be reported as a measurement.
    """
    from colorist.measure import _rgb_to_hsv

    values = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    boolean = np.asarray(mask, dtype=bool)
    if boolean.shape != values.shape[:2]:
        raise CorpusError("mask shape does not match the image")
    if not boolean.any():
        return float("nan")

    sampled = values[boolean]
    if statistic == "hsv_saturation_median":
        _, saturation, _ = _rgb_to_hsv(sampled)
        return float(np.median(saturation))
    if statistic == "r_minus_b_median":
        return float(np.median(np.abs(sampled[:, 0] - sampled[:, 2])))
    if statistic == "luma_median":
        return float(np.median(sampled @ np.array([0.2126, 0.7152, 0.0722])))
    raise CorpusError(f"unknown statistic {statistic!r}")


# ---------------------------------------------------------------------------
# The delivery leg.
#
# A corpus item's carrier is lossless and is the reference. The DELIVERY is the
# artefact a colourist would actually hand over, and it is what the harness
# scores, so the corpus has to produce one and has to say what the codec cost.
#
# THE TRAP THIS CODE EXISTS TO AVOID
#
# The obvious design is to measure the delivery against the analytic truth, store
# that residual, and hand it back as the tolerance a consumer should allow. That
# is a circular oracle: the consumer then asserts residual <= residual and the
# check cannot fail. Concretely, drop -color_range from the encode so a
# full-range file is tagged limited, and every patch's measured error grows by
# the 255/219 expansion, the stored allowance grows to match, and the corpus
# certifies a delivery wrong by 6 percent of range.
#
# So the acceptance bound is NOT measured from the file. It is derived from the
# delivery profile: bit depth, range, and the BT.709 matrix. Then a measurement
# is being checked against something that was not measured from the artefact.
# ---------------------------------------------------------------------------

#: BT.709 YCbCr to RGB coefficients. The BLUE coefficient is the largest and is
#: therefore what sets the worst-case bound. Using the red one, 1.5748, produces
#: a ceiling that a real ProRes measurement exceeds, which is how a wrong model
#: announces itself.
BT709_CR_TO_R: Final[float] = 1.5748
BT709_CB_TO_B: Final[float] = 1.8556
BT709_CB_TO_G: Final[float] = 0.1873
BT709_CR_TO_G: Final[float] = 0.4681


def _pix_fmt_bit_depth(pix_fmt: str) -> int:
    """Bit depth of an ffmpeg planar YUV pixel format name."""
    for depth in (16, 14, 12, 10):
        if f"p{depth}" in pix_fmt:
            return depth
    return 8


def predicted_quantisation_ceiling(pix_fmt: str, video_range: str) -> float:
    """Worst-case RGB error from YCbCr quantisation alone, in 8-bit code units.

    Derived from the pixel format and the range, NOT measured from any file. That
    independence is the entire point: it gives a bound that a measurement can be
    checked against without checking a measurement against itself.

    A half code step in Y and in chroma propagate into RGB through the BT.709
    matrix, and blue is the worst channel because 1.8556 is the largest
    coefficient. Measured against this bound on the reference scene:

        h264-yt-sdr, 8 bit limited     ceiling 1.6384, observed 1.1539, ratio 0.70
        prores-422hq, 10 bit limited   ceiling 0.4096, observed 0.4136, ratio 1.01

    **The bound is quantisation only and ProRes exceeds it by one percent.** That
    residual is chroma subsampling, which averages neighbouring samples and is
    not in this model. So this is a scale check, not a hard bound, and a caller
    should assert the observed floor is the right SIZE rather than strictly
    under. That still catches the failure worth catching: a range mistake costs
    the 255/219 expansion, roughly 16 code values, which is an order of magnitude
    away and impossible to miss.
    """
    depth = _pix_fmt_bit_depth(pix_fmt)
    full = (1 << depth) - 1
    if video_range == "limited":
        luma_span = (235 - 16) << (depth - 8)
        chroma_span = (240 - 16) << (depth - 8)
    elif video_range == "full":
        luma_span = chroma_span = full
    else:
        raise CorpusError(f"unknown range {video_range!r}, expected limited or full")

    luma_half = 0.5 / luma_span
    chroma_half = 0.5 / chroma_span
    worst = max(
        luma_half + BT709_CR_TO_R * chroma_half,
        luma_half + (BT709_CB_TO_G + BT709_CR_TO_G) * chroma_half,
        luma_half + BT709_CB_TO_B * chroma_half,
    )
    return worst * 255.0


def delivery_interior_mask(layout: ChartLayout, *, edge_margin: int = 2) -> np.ndarray:
    """True where a delivery has a defensible per-patch expectation.

    A subsampled delivery averages chroma across a patch boundary, so a pixel
    beside an edge carries colour belonging partly to its neighbour and has no
    expected value derivable from its own patch's reflectance. Comparing a
    delivery to the analytic truth per pixel across the whole frame is therefore
    a category error, not a strict measurement, and this mask is how the code
    declines to make it.
    """
    if edge_margin < 0:
        raise CorpusError("edge_margin must not be negative")
    width, height = layout.resolution()
    interior = np.zeros((height, width), dtype=bool)
    for cell in range(layout.cells):
        x0, y0, x1, y1 = layout.rect(cell)
        if x1 - x0 <= 2 * edge_margin or y1 - y0 <= 2 * edge_margin:
            continue
        interior[y0 + edge_margin : y1 - edge_margin, x0 + edge_margin : x1 - edge_margin] = True
    return interior


# ---------------------------------------------------------------------------
# Combined defects and equal-distance pairs.
#
# Validation property 10 needs randomised and COMBINED defects, because a metric
# fitted to one family at a time can be defeated by two at once. Property 13
# needs pairs of items equally far from the reference by a whole-image measure
# but carrying DIFFERENT per-dimension defects, which is the test that kills a
# metric recognising overall distance but not meaning.
#
# Both need a stated distance, or "equally far" is not a claim. The distance used
# here is the root mean square difference in display code over the whole frame,
# in 8-bit code units. It is deliberately the crudest reasonable choice: a metric
# that can be fooled by it is fooled by the thing a naive observer would call
# "how different do these look", which is exactly the null metric property 13 is
# aimed at.
# ---------------------------------------------------------------------------


def frame_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Root mean square display-code difference, in 8-bit code units."""
    left = np.clip(np.asarray(a, dtype=np.float64), 0.0, 1.0)
    right = np.clip(np.asarray(b, dtype=np.float64), 0.0, 1.0)
    if left.shape != right.shape:
        raise CorpusError("frame_distance needs two images of the same shape")
    return float(np.sqrt(np.mean((left - right) ** 2)) * 255.0)


def inject_many(
    image: np.ndarray, defects: Sequence[tuple[str, float, str]]
) -> np.ndarray:
    """Apply several defects in order, for the combined case property 10 wants.

    Order matters and is not commutative: a chroma scale after a tone compression
    is not the same image as the reverse, because the tone curve is non-linear.
    The sequence is therefore part of the item's identity and is recorded rather
    than sorted into some canonical order.
    """
    result = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    for family, severity, injector in defects:
        result = inject(result, family, severity, injector=injector)
    return result


def severity_for_distance(
    image: np.ndarray,
    family: str,
    target: float,
    *,
    injector: str = "primary",
    tolerance: float = 1e-3,
    max_iterations: int = 60,
) -> float:
    """Find the severity whose defect sits ``target`` away from ``image``.

    Bisection on severity. Distance is monotonic in severity for every family
    here, which is asserted by the monotonicity tests, so bisection is sound.

    Raises rather than clamping when the target is beyond what severity 1.0 can
    reach. Returning the closest available severity would silently produce a pair
    that is NOT equal distance, which is the one property the caller wanted.
    """
    reference = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    reachable = frame_distance(reference, inject(reference, family, 1.0, injector=injector))
    if target > reachable:
        raise CorpusError(
            f"{family!r} with the {injector!r} injector reaches only "
            f"{reachable:.4f} code values at severity 1.0, short of {target:.4f}"
        )

    low, high = 0.0, 1.0
    for _ in range(max_iterations):
        middle = (low + high) / 2.0
        distance = frame_distance(
            reference, inject(reference, family, middle, injector=injector)
        )
        if abs(distance - target) <= tolerance:
            return middle
        if distance < target:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def equal_distance_pair(
    image: np.ndarray,
    first: str,
    second: str,
    target: float,
    *,
    injector: str = "primary",
) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """Two images equally far from ``image`` but damaged in different dimensions.

    Returns the pair and the severities that produced it. Property 13 asserts
    that a metric scores these DIFFERENTLY per dimension despite their equal
    whole-image distance, so a metric that only measures overall difference
    fails.
    """
    reference = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    severities = (
        severity_for_distance(reference, first, target, injector=injector),
        severity_for_distance(reference, second, target, injector=injector),
    )
    return (
        inject(reference, first, severities[0], injector=injector),
        inject(reference, second, severities[1], injector=injector),
        severities,
    )
