<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Practitioner notes: craft-consensus evidence (tier C)

These are our own notes on two publicly available colorist walkthroughs. They exist to
record what the project took from named practitioners, and where those practitioners
disagree, so that reference files can cite craft consensus honestly instead of presenting
one colorist's habit as a rule.

This file is original analysis. It is not a transcript, a summary substitute, or a
reproduction of either video. Quotations are short and attributed. Watch the sources
themselves for their actual content.

## Sources

- Darren Mostyn, "How I Grade this Ad - MASTERCLASS (UK Broadcast PRO Colorist)",
  <https://www.youtube.com/watch?v=dxL7tclBlnY>, 13:37, viewed 2026-07-19.
  A real broadcast commercial, ARRI LogC3 source, graded in DaVinci Resolve.
- Dante Pascarella, "5 Color Grading Secrets That Make Pro Filmmakers Stand Out",
  <https://www.youtube.com/watch?v=-k87m157X4I>, 6:59, viewed 2026-07-19.
  S-Log3 source, DaVinci Resolve.
- Structural anchor for this project's five-pillar taxonomy: Alex Runhaar,
  "How to become the BEST COLORIST", <https://www.youtube.com/watch?v=ucoe-dvPoME>,
  viewed 2026-07-19.

Evidence tier: C, meaning named practitioners demonstrating their own craft. Tier C is
admissible in this repository only for `references/look-design/` and
`references/cinematography/`, where primary standards do not exist. It never supports a
numeric threshold or a claim about what this repository's code does.

## Where the two demonstrations converge

**Color management first, corrections in a wide working space, the creative look
downstream, the display transform last.** Mostyn transforms from LogC3/AWG3 into DaVinci
Wide Gamut, grades there, and transforms out to Rec.709 at 2.4. Pascarella balances and
sets contrast before his creative LUT, which he places on the last node. Two colorists
working from different cameras and different node habits arrive at the same ordering.
This project hard-codes that ordering as IDT, corrections, look, ODT.

**Correct while viewing through the look, not before it.** Mostyn inserts a Kodak 2383
print emulation early and keeps adjusting upstream nodes while watching the composite,
because a correction tuned without the look does not survive the look landing. This is
why the project's gates evaluate the final output rather than an intermediate, and why a
look change re-enters the verify loop.

**Scopes decide, and every change gets checked.** Mostyn reads the waveform before
touching anything, samples skin on the vectorscope, and toggles each node on and off after
working it, in his words to "check that I'm actually improving the image". That habit is
the human form of what this project automates: measure first, then verify the change
against numbers rather than against impression.

**One frame is not the shot.** Mostyn's advice is blunt: "never just take your first frame
as the grading frame". His subject's face brightens as it moves through the light. This
project samples at the quarter, half, and three-quarter positions of each shot and pools
the medians. It does not implement clean-frame rejection or transition quarantine, so the
sampled frames are the evidence, not a guarantee about every frame.

**Skin gets protected when the rest of the frame takes an aggressive move.** Mostyn keys
the scarf and windows it away from skin before desaturating. Pascarella isolates skin on
its own layer and grades everything behind it. The project ships skin-band gates, but note
the asymmetry: the chromatic half of that technique compiles into a LUT, and the spatial
half does not.

## What each demonstration adds on its own

Mostyn works from a fixed node tree whose slots have assigned meanings, with most slots
unused on any given shot. The value is a stable structure to edit rather than a tree
rebuilt per shot. He also mentions delivering many client versions of a multi-shot spot,
which is the same problem this project answers with parameter manifests: the parameters
are the source of truth and the rendered artifact is their deterministic compilation. He
chooses tools empirically, trying the highlight tool against curves and looking at the
result. His finishing texture work, halation and bloom at low impact after the display
transform, is spatial and therefore permanently outside this project's LUT-only scope.

Pascarella is the more useful of the two for this project's math, because he demonstrates
that "saturation" names more than one operator. A standard saturation control and an HSV
S-channel gain, with hue and value held, behave differently in luminance. This project's
operator interpolates toward the Rec.709 luma axis in the log2 grading space; his S-gain
preserves HSV value instead. Both are pure color-to-color maps and both are therefore
LUT-compilable, but they are not the same operator and the project implements only one of
them. His claim that ordinary saturation damages luminance is testable with this
repository's own measurement tools, and it is a reasonable v1.1 investigation.

His "milky shadows" treatment, a lifted toe with pulled highlights, is worth recording for
a specific reason: it deliberately holds the shadow floor high. That is a direct
counterexample to treating any shadow-floor gate value as a law. Those values encode a
taste, and the project labels them unvalidated defaults for exactly this reason.

He also demonstrates hue-band adjustments, which are color-only and LUT-expressible, and
therefore sit on the v1.1 roadmap. The caveat that belongs in LIMITS: a purely chromatic
key does compile into a LUT, but a real qualifier is cleaned spatially with blurs and
garbage mattes. A LUT cannot do that, so color-only keys can posterize at key edges on
noisy footage.

## Where they diverge, recorded as divergence

Look placement. Mostyn parks the look mid-tree, because he prefers certain plugins to
operate on Rec.709 values downstream of it. Pascarella places his at the end. Mostyn
himself notes that most colorists put the display transform at the very end, and that HDR
delivery forces end placement.

These placements are not interchangeable. Non-linear transforms do not generally commute,
so moving a look across a non-linear stage changes the result. Reference files must not
present either arrangement as the rule. This repository fixes one placement and tests it,
which is a claim about this repository and not about grading in general.

## Roadmap items that originate here

1. Curve-family corrections, all LUT-compilable and requiring no new architecture:
   saturation versus luminance, hue-band adjustments, luminance versus saturation,
   hue versus hue.
2. A selectable alternative saturation operator, the HSV S-gain.
3. A named "milky" contrast archetype as a look preset.
4. Color-only skin protection, shipped with the posterization caveat stated.

Permanently out of scope unless the architecture changes: spatial windows, tracking,
matte cleanup, and texture finishing such as halation, bloom, and grain.
