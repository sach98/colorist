---
name: colorist
description: Use when grading, color-correcting, or QC-checking video with ffmpeg; when log footage (S-Log3, LogC3, LogC4, V-Log, C-Log3) needs conversion to Rec.709; when whites or skin look wrong, shots do not match across cuts, or a delivery needs numeric color QC or broadcast-range checks; when the user says grade this, fix the color, check my export, or make shots match.
license: MIT
---
<!-- SPDX-License-Identifier: MIT -->

# colorist

An AI colorist that measures before it grades. Core discipline: **measure, decide, apply, verify.** Numbers from decoded pixels drive every decision; numeric gates decide whether output ships. You (the agent) choose intent and targets; deterministic solvers compute values; ffmpeg applies them; gates verify. You never judge color from a rendered image by eye, and never hand-tune a number a solver can compute.

## Setup preflight

Run once per session: `ffmpeg` present with the `scale`, `lut3d`, and `scdet` filters (`ffmpeg -filters`) and the `ffv1` encoder (`ffmpeg -encoders`, since ffv1 is an encoder not a filter), Python 3.11 to 3.13 with the package installed (`python -m colorist --help`). Missing capability = say exactly what is missing and stop; no degraded guessing. ffmpeg and ffprobe are resolved from PATH, or from COLORIST_FFMPEG / COLORIST_FFPROBE if set.

## The commands (this is the whole CLI)

`--preset` is required and has no default: the shipped presets are provisional (see the honesty note at the end). For `qc` and `consistency`, `--out` is a run DIRECTORY for the reports, masks, and any review PNGs, and existing reports are not overwritten. For `propose-cuts` and `confirm-cuts`, `--out` is a CSV FILE path.

Two preset facts decide whether a run can PASS, so state them when a user writes their own. Hard gates are always required. A soft gate is required only when its `coverage` name appears in the preset's `required_coverage`; a soft gate outside that list is diagnostic, so absent evidence reports `SKIPPED_ABSENT_EVIDENCE` and the run can still PASS. The shipped `interview` preset requires `whites`, `shadows`, and `highlights` and leaves `skin` optional, because footage with no faces is normal and is not a defect.

Every processing command runs a preflight first and refuses to start unless ffmpeg and ffprobe both report version 8.x and ffmpeg lists the `scale`, `lut3d`, and `scdet` filters and the `ffv1` encoder. If a user reports an immediate `PreflightError`, their ffmpeg is the problem, not their footage.

| Command | Invocation | Renders |
|---|---|---|
| qc | `python -m colorist qc FILE --preset interview --deliver h264-yt-sdr --out DIR [--source-reference SRC] [--encoding PAIR]` | No |
| consistency | `python -m colorist consistency FILE --cuts CUTS.csv --preset interview --deliver h264-yt-sdr --out DIR [--encoding PAIR] [--approve-short-shots]` | Yes, always |
| propose-cuts | `python -m colorist propose-cuts FILE --out PROPOSAL.csv [--threshold T] [--min-shot N]` | No |
| confirm-cuts | `python -m colorist confirm-cuts PROPOSAL.csv --out CUTS.csv` | No |

Additional shared flags on qc and consistency, from `--help`: `--mask-review` (write opt-in source-mask contact sheets), `--input-range`, `--input-matrix`, `--input-transfer`, `--input-primaries` (declare source conversion when tags are absent), and `--confirm-metadata-override` (proceed after a declared-vs-tagged conflict is shown). consistency also takes `--workdir`. Run `python -m colorist <command> --help` for the exact surface.

qc verifies a delivered file against the expected `--deliver` profile: color tags, native YUV sample range (every frame), and the gate battery. Grade-introduced clipping is a hard gate but needs the pre-grade file: pass `--source-reference`, or that gate reports INDETERMINATE rather than being skipped. consistency always encodes a delivery, so `--deliver` is required. A creative-look grade and a prose-only advise are library and agent operations in v1, not commands; use `references/look-design/` and the agent prompts.

Exit codes: 0 PASS, 2 FAIL, 3 INDETERMINATE, 4 ERROR. (argparse also exits 2 on a usage error, so 2 alone is not uniquely FAIL for a machine consumer; read the report state.) INDETERMINATE is honest (required evidence absent), not a malfunction. Reports (json + md) state every gate's measured value, threshold, and domain.

How rendering works (do not reinvent it): each shot renders as its own segment FROM SOURCE through an explicit float-RGB LUT graph into a lossless RGB mezzanine, then one delivery encode. There is no sendcmd or runtime-command path in this tool, deliberately.

## Encoding declaration (never guess)

The tool does NOT detect log footage or suggest a pair. You declare it with `--encoding`; omitting it means display-referred Rec.709 passthrough.

1. `ffprobe` color tags and container hints are EVIDENCE only; they cannot express a vendor log pair.
2. For log footage, choose the (curve, gamut) pair explicitly from the supported set: slog3_sgamut3cine, logc3ei800_awg3, logc4_awg4, vlog_vgamut, clog3_cgamut. An unsupported value is refused by name.
3. If a declaration conflicts with the file's own range or matrix tags, the run stops and shows the conflict; pass `--confirm-metadata-override` to make the declaration win on purpose.

## Cut lists

`propose-cuts` (scdet) writes a scored, complete, non-authoritative proposal. Show it; the user reviews it, then `confirm-cuts` turns it into the authoritative `start_frame,end_frame` CSV the grading workflows require. A proposal file is never silently accepted as authoritative.

## Feedback triage (when the user dislikes a result)

The grade is a parameter manifest; the video is its compilation. Every iteration re-renders from the ORIGINAL source. Never re-grade an output file; never discard the manifest.

| Feedback | Layer | Action |
|---|---|---|
| Vague ("something is off") | none yet | Run advise: measure, show per-shot findings, ask which matches |
| Named defect ("shot 7 too warm") | normalization | Re-run that solver for those shots only |
| Taste ("too warm overall", "too flat") | look | Adjust look parameters; per-shot normalization survives |
| Direction ("make it teal instead") | look | Rebuild look; normalization survives |
| "I like it, your gate is wrong" | gates | Point `--preset` at an adjusted copy with the value they want, on the record; a first-class per-run waiver is roadmap, not a CLI surface |

## Agents

For deep work, dispatch subagents with these prompt files (read the file, use as the subagent prompt): agents/color-theory.md, agents/industry-standards.md, agents/cinematography.md, agents/detail-qc.md, agents/look-design.md. Navigate knowledge via references/INDEX.md; load only what the task needs.

## Data locality

All pixel processing is local. A still or thumbnail sent to a model provider requires explicit user opt-in first, once per session. qc never transmits anything.

## Red flags: stop and re-read this skill

- About to describe color quality from looking at a frame: measure instead.
- About to type a gain/EV/saturation number by hand: solve it.
- About to grade the previous output file: re-render from source.
- About to trust `color_space=unknown` tags or guess a log curve: the user declares `--encoding`; the tool does not guess.
- About to average neutrals that disagree: report the clusters (mixed light).
- Gates failed but shipping anyway: put the intended value on the record in an adjusted preset rather than ignoring the gate.
- About to hand-build an ffmpeg grading chain (eq, curves, sendcmd, a self-made conversion LUT): the tested pipeline exists; use it. eq and curves silently negotiate through yuv444p and 8-bit rgb24 mid-graph (measured on ffmpeg 8.1.2), and hand-made LUTs skip the vendor-vector verification.
