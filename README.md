# colorist

<!-- SPDX-License-Identifier: MIT -->

**An AI colorist that measures before it grades.**

Point it at a delivered video and an expected profile. It measures the actual pixels per shot, checks the delivery's color tags and sample range, runs numeric gates, and returns an honest terminal state: PASS, FAIL, INDETERMINATE (required evidence absent), or ERROR. For the grading workflows it computes corrections in closed form, renders them through a verified ffmpeg pipeline, then re-measures the delivered file. No Resolve, no Studio license, no GPU. All pixel processing runs locally; see Data locality below for the one narrow exception.

```bash
python -m colorist qc your_export.mp4 --preset interview --deliver h264-yt-sdr --out ./qc-run
```

You get a report card written to the run directory: every gate's measured value, threshold, and measurement domain, and the terminal state. That is the wedge; the rest of the tool grades.

## What it does

Four commands ship in v1. For `qc` and `consistency`, `--out` is a run DIRECTORY (reports, masks, review PNGs) and existing reports are not overwritten; for `propose-cuts` and `confirm-cuts`, `--out` is a CSV FILE path.

| Command | What happens |
|---|---|
| `qc FILE --preset P --deliver PROFILE --out DIR` | Verify a delivered file against the expected profile: check its codec, pixel format, container, and color tags, scan every frame's native sample range, run the gates, write a numeric report. No rendering. Pass a distinct pre-grade file with `--source-reference` to also measure grade-introduced clipping. The tool checks sampled, downscaled frame luma for spatial rank correspondence before comparing every frame. Missing, flat, or non-corresponding evidence makes that hard gate INDETERMINATE. Supplying the delivery itself is an ERROR. |
| `consistency FILE --cuts CSV --preset P --deliver PROFILE --out DIR` | The most common defect in edited interviews: white balance and exposure changing at every cut. Measures per-shot neutrals on both white axes, solves per-shot corrections in closed form, re-renders from source, encodes the delivery, and verifies it. `--deliver` is required. |
| `propose-cuts FILE --out CSV` | Run scene detection and write a scored, complete, non-authoritative cut proposal for you to review. |
| `confirm-cuts PROPOSAL --out CSV` | Turn a reviewed proposal into the strict authoritative cut list the grading workflows require. |

A creative-look grade (consistency plus a look LUT compiled per shot) is a library operation in v1 via `grade_file`; `advise` is an agent prompt pattern (see the agent prompts in `agents/` and `references/look-design/`), not a shipped function. Both are on the roadmap as commands.

## The discipline

1. **Measure, decide, apply, verify.** Frame statistics drive decisions; numeric gates decide shipping. Model eyeballs are never the instrument (they are measurably unreliable for subtle color discrimination).
2. **Agents choose intent; solvers compute numbers.** "Neutralize to D65, hold faces steady" is a decision; the gains are arithmetic (closed-form from neutral medians, luma-preserving).
3. **Honest uncertainty.** No neutrals in frame yields null, not a fabricated measurement. Disagreeing neutral regions refuse a global white balance and report clusters. Required evidence absent makes the run INDETERMINATE, never a vacuous PASS. A clipping source reference is accepted only when sampled, downscaled luma rasters retain enough rank structure and their median Spearman correlation meets the reported threshold. Flat evidence and non-corresponding content are INDETERMINATE; the delivery itself is an ERROR.
4. **Every iteration re-renders from source.** The grade is a versioned parameter manifest; the video is its compilation. Generational damage is structurally impossible.

## Supported input (v1)

Log pairs: **S-Log3/S-Gamut3.Cine, ARRI LogC3 EI800/AWG3, ARRI LogC4/AWG4, V-Log/V-Gamut, C-Log3/Cinema Gamut**, plus Rec.709 display-referred passthrough (the default when no `--encoding` is given). Each log CURVE is checked against the manufacturer's own document, with the neutral anchors, formulas, and file hashes recorded in `tests/vectors/`. The GAMUT matrices come from colour-science, not from independent manufacturer primary vectors, so the proof is of the transfer curve, not the full camera gamut. Containers mp4/mov/mkv via ffmpeg. You declare the encoding with `--encoding`; the tool does not detect log footage or suggest a pair for you, and it refuses an unsupported declaration by name. Standard metadata cannot identify a vendor log pair, so the declaration is yours to make. If declared metadata conflicts with the file's own tags, the run stops and shows the conflict rather than guessing.

## Honesty section, read before trusting defaults

The shipped gate values are **unvalidated defaults**. They are not the output of a published validation study, and there is no corpus, labeled dataset, false-pass rate, or reproducible report in this repository to back them: they encode one production's contrast taste, and on a real grade the author approves they both passed a version carrying per-object casts and would have failed a look the author considers correct. Treat them as worked examples, not thresholds to trust. Because they are provisional, no preset is a default: you select one with `--preset` every run. The white-balance gates evaluate per region and refuse to pool disagreeing regions on either white axis. The measurement LOOP is the product; the numbers are a starting point. In v1 the way to put your creative intent on the record over a soft gate is to point `--preset` at your own copy with your values; a first-class per-run waiver is on the roadmap, not a shipped CLI surface.

One preset mechanism deserves explicit mention because it decides whether a run can PASS. Hard gates are always required. Soft gates are required only when their `coverage` name is listed in the preset's `required_coverage`: a soft gate outside that list is diagnostic, so absent evidence reports `SKIPPED_ABSENT_EVIDENCE` and the run can still PASS. The shipped `interview` preset requires `whites`, `shadows`, and `highlights`, which are computable on any footage, and leaves `skin` optional because legitimate footage (b-roll, landscape, product) contains no faces and that is not a defect. If you write your own preset, list every coverage you actually want to gate on, or its absence will be silent.

## Install

Requires **Python 3.11, 3.12, or 3.13** (a `colour-science` constraint; the package refuses to import on anything older with a clear message) and **ffmpeg 8.x** with the `scale`, `lut3d`, `scdet`, and `ffv1` features. The CI conformance lane pins ffmpeg 8.1.2, which is the build every empirical number in this repository was measured on.

```bash
# ffmpeg 8.x is REQUIRED (needs scale, lut3d, scdet, ffv1).
brew install ffmpeg          # macOS: currently ships 8.x

# Debian/Ubuntu: check before you trust the distribution package. Ubuntu 24.04
# LTS ships ffmpeg 6.1.1, which this project refuses. If `ffmpeg -version`
# reports anything other than 8.x, install a static 8.x build from
# https://github.com/BtbN/FFmpeg-Builds/releases and point COLORIST_FFMPEG and
# COLORIST_FFPROBE at it.
sudo apt install ffmpeg && ffmpeg -version | head -1

git clone https://github.com/sach98/colorist ~/.claude/skills/colorist
cd ~/.claude/skills/colorist
python3 -m venv .venv && .venv/bin/pip install -e .   # python3 must be 3.11-3.13

# Verify the install and see the commands:
.venv/bin/python -m colorist --help

# A real command that reaches a clean state: propose cuts on the bundled clip.
# It finds the scene boundaries and writes a scored proposal (exit 0):
.venv/bin/python -m colorist propose-cuts tests/assets/smoke_scenes.mp4 --out /tmp/cuts.csv
```

Running `qc` on that bundled clip is instructive rather than clean: the clip deliberately includes an SMPTE bars scene with a below-legal pluge, so `qc ... --deliver h264-yt-sdr` returns FAIL on the delivery range gate. That is the tool catching a genuine delivery defect, not a malfunction.

ffmpeg and ffprobe are found on `PATH`. If they are installed somewhere `PATH` does not see, set `COLORIST_FFMPEG` and `COLORIST_FFPROBE` to their absolute paths. Every processing command runs a preflight first: it refuses to touch a frame unless both tools report ffmpeg 8.x and ffmpeg lists the `scale`, `lut3d`, and `scdet` filters and the `ffv1` encoder. Resolution alone proves nothing, so an override pointing at something that is not ffmpeg is rejected by name rather than producing numbers from a build this project never ran on.

Claude Code users get the full skill (SKILL.md plus five specialist agents) by cloning into `~/.claude/skills/colorist/`; optionally copy `agents/*.md` into `~/.claude/agents/`. The CLI works standalone with no AI at all.

## The five agents

The architecture follows the five masteries from Runhaar's "How to become the BEST COLORIST" (youtube.com/watch?v=ucoe-dvPoME): **color-theory** (encodings, transforms, LUT math), **industry-standards** (live research, never answers from memory), **cinematography** (reads the lighting before anyone grades), **detail-qc** (the measurement gatekeeper), **look-design** (taste proposes, gates dispose). Each agent's knowledge lives in `references/` (26 evidence-tagged files, indexed).

## Data locality

The CLI does all pixel processing locally: decode, measure, grade, and encode never leave your machine, and `qc` in particular transmits nothing. The one exception is agent-driven use: when an agent inspects a still or thumbnail visually, that image, and any measurements or file paths placed in a prompt, go to whatever model provider the agent host uses, and only after an explicit per-session opt-in. So the accurate statement is narrow: CLI pixel processing is local; agent transmission of stills, derived numbers, and paths depends on the host and your consent.

## Limits

Real limits documented in [LIMITS.md](LIMITS.md): no spatial secondaries (windows, tracking, qualifier cleanup), no HDR yet, no texture finishing, SDR Rec.709 delivery only, and the gate-validation status above. The FAQ covers the inevitable Resolve question.

## Licensing

Every tracked source, doc, preset, and asset file carries an `SPDX-License-Identifier` or a `.license` sidecar (the `LICENSE`, `LICENSE-references`, and `.gitignore` files are the exceptions, being license text and tooling config). `LICENSE` contains the full MIT text; `LICENSE-references` summarizes the CC-BY-4.0 grant and links its full legal text.

| What | License |
|---|---|
| Code, SKILL.md, agents, presets, tests, tooling | MIT |
| `references/` knowledge base | CC-BY-4.0 |
| `docs/` (design notes, spike results, research notes) | CC-BY-4.0 |
| `tests/vectors/*.json` | MIT, but each contains short manufacturer quotations used for verification, attributed inline |
| Test clip `smoke_scenes.mp4` (self-authored, synthetic) and anything derived from it | CC0-1.0, public domain (see [tests/assets/ATTRIBUTION.md](tests/assets/ATTRIBUTION.md); reproduce with `tools/make_test_clip.py`) |

## Credits

Structure: Alex Runhaar's five-pillar taxonomy. Craft evidence: Darren Mostyn and Dante Pascarella, cited from their published videos; our own analysis notes are in `docs/research/practitioner-notes.md`. Format precedent for the reference pack: meodai/skill.color-expert. Color math: colour-science. Built measure-first because of hard lessons on real deliveries, several of which are documented inside as worked examples.
