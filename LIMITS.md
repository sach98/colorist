# Limits

<!-- SPDX-License-Identifier: MIT -->

Honest boundaries, stated before you hit them.

## Input

- Supported log pairs only (see README ingest matrix). Identification is explicit: metadata is evidence, you confirm the pair. Unknown encodings are refused by name.
- VFR (variable frame rate) input is refused by the grading workflows in v1 (timestamp integrity across per-shot rendering is not guaranteed); qc runs on it, decoding with passthrough timing so each stored frame is measured exactly once.
- The `--source-reference` clipping check authenticates the reference by spatial rank correspondence, which a grade preserves and unrelated content does not. It holds through severe grades: measured on encoded test media, brightness lifts producing 24 to 33 percent introduced clipping still correlate 0.795 to 0.997. Past that point the delivery is clipped so far that too little rank structure survives to prove the reference matches (a lift correlating 0.32 was refused), and introduced clipping is reported INDETERMINATE rather than computed against a reference that could not be verified. The independent delivery range gate still inspects every frame in that case.
- Damaged or partially-decodable files terminate ERROR, not a best-effort guess.

## Corrections

- v1 corrections are per-shot GLOBAL: white balance gains, exposure, pivoted contrast, saturation, plus one look LUT. All compile into a single 3D LUT per shot.
- NO spatial operations: no power windows, no masks, no tracking, no matte cleanup, no local dodge/burn. A LUT maps color to color; it cannot know where a pixel is.
- Colour-only isolation (e.g. "protect skin-colored pixels") is LUT-expressible and on the v1.1 roadmap with a stated caveat: real qualifiers clean their mattes spatially; a LUT cannot, so hard color keys can posterize at edges on noisy footage.
- No texture finishing: no halation, bloom, grain, or film weave.
- No denoise. Grading amplifies source noise, especially from log footage pushed hard; denoise before grading (documented in references/look-design/building-a-look-stack.md), using your own tools.

## Measurement

- No neutrals in frame means no white-balance evidence: the tool reports null and refuses automatic WB rather than inventing a reference.
- Regions that disagree on either white axis (mixed lighting) refuse a single global WB; you get the per-region clusters and a limitation notice.
- Shots under 3 frames are measured, but their affected gates are marked INDETERMINATE and automatic correction of them is refused unless you pass `--approve-short-shots`, which is recorded and still leaves the gates INDETERMINATE.
- Gate values are UNVALIDATED defaults. There is no corpus, labeled dataset, or reproducible validation report in this repository behind them; they encode one production's taste, and a grade the author approves would fail some of them. The white-balance gates evaluate per region on both white axes. No preset is a default; you select one with `--preset` each run. The v1 override is an adjusted preset copy carrying your values; a first-class per-run waiver record is roadmap, not a shipped CLI surface.

## Delivery

- v1 delivers SDR Rec.709: h264-yt-sdr (mp4) and prores-422hq (mov) profiles. No HDR (PQ/HLG) yet.
- Unsupported input/output combinations are refused by name.

## Platform

- Tested on the Claude Code skill host; the CLI is host-independent. Other agent-skill hosts degrade to advisory use of the references.
- The industry-standards agent declines to answer from memory when it has no live web access; that is by design.

## Privacy

- All pixel processing is local. qc transmits nothing, ever. Agent workflows that would send a still or thumbnail to a model provider require explicit opt-in, once per session. Reports contain measurements and file paths; review before sharing them.
