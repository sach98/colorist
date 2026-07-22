# Common defects catalog

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Symptom, measurement signature, likely cause, and project response. Some defects are numerically measurable; others, such as borderline banding, also need human visual review.

## Color cast on neutrals

Signature: frozen neutral regions with R minus B or green-axis disagreement of a consistent sign across sampled frames. Possible causes include camera white balance, mixed light, or a grade error. Project response: solve closed-form per-shot gains only when neutral evidence is unimodal. Opposed casts can cancel in a pooled mask, so the tool records connected regions separately [E: src/colorist/measure.py].

## Cross-cut alternation

Signature: per-shot neutral medians alternate sign, such as one camera reading warmer and another cooler. Project response: measure each shot, normalize eligible shots before a global look, and verify the rendered delivery [E: src/colorist/workflow.py] [E: src/colorist/verify.py].

## Range double-squeeze

Signature: a limited-range signal is converted or interpreted as limited-range again, reducing contrast. Project response: declare range at conversion edges and inspect the decoded delivery as well as source-relative measurements [E: src/colorist/grade.py] [E: src/colorist/verify.py].

## Wrong or missing color tags

Signature: `ffprobe` reports unknown or mismatched color range, space, transfer, or primaries against the selected profile. Project response: write explicit tags at encode and verify the delivered file against the profile [E: src/colorist/grade.py] [E: src/colorist/verify.py].

## Hidden pipeline conversions

Signature: a processing chain negotiates through unexpected pixel formats. The repository observed yuv444p and rgb24 around one FFmpeg 8.1.2 graph with `eq` and `curves`, then made negotiated-format checks part of the path [E: docs/spike-verdict.md] [E: src/colorist/grade.py].

## Crushed shadows / clipped highlights

Signature: luma p1 near the floor with a histogram wall can indicate crushed shadows; p99 near the ceiling with nonzero clipped fraction can indicate clipping. Project response: compare source and output clipping to distinguish grade-introduced clipping from source clipping, and treat an elevated floor as a possible intentional look [E: src/colorist/verify.py] [E: presets/gates/interview.yaml].

## Oversaturated skin

Signature: a frozen skin-candidate mask has an HSV saturation median outside the selected working interval. Verify that the mask samples skin before acting [E: src/colorist/measure.py, _skin_mask and write_mask_sheet]. This v1 tool can report the condition but does not implement spatial skin-band corrections [E: repository LIMITS.md].

## Banding and posterization

Signature: visible stepping on smooth gradients, sometimes accompanied by sparse unique values in a gradient region after aggressive processing of 8-bit material. The project uses float math and a gbrp16le FFV1 mezzanine to reduce avoidable intermediate error [E: docs/spike-verdict.md]. Numeric detection of borderline banding is weak; project guidance: include visual review for this class. No maintained human visual-regression set is claimed here.
