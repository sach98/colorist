# colorist: design spec (v2)

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

> **This is the original design document, not the shipped product contract.** It
> describes the intended v1 and beyond, and it deliberately still names features
> that are NOT implemented in the shipped tool: a `grade` and `advise` command,
> cost tiers, MXF/HEVC/ProRes containers, VFR handling, transition quarantine,
> flash rejection, source-relative delta E and temporal gates, and multiple genre
> presets. What actually ships is described by `README.md`, `SKILL.md`, and the
> code; the shipped commands are `qc`, `consistency`, `propose-cuts`, and
> `confirm-cuts`. Read this file for the reasoning behind the architecture, not as
> a list of available behavior.

Date: 2026-07-19 (v2, same day; v1 in git history)
Status: design document; superseded as a behavior contract by the shipped README, SKILL, and code
Provenance: Runhaar, "How to become the BEST COLORIST" (youtube.com/watch?v=ucoe-dvPoME), whose five masteries structure the agent architecture. v1 was refined through a live prior-art sweep and two hostile design reviews; v2 folds all 15 findings of the second, including two verified empirically before revision (ffmpeg 8.1.2 auto-negotiates gbrp graphs through yuv444p and 8-bit rgb24 when eq/curves are present; colour-science 0.4.7 requires Python >=3.11).

## 1. Purpose and positioning

A public GitHub repo (`sach98/colorist`) containing a Claude skill plus five agents that together behave like a working digital colorist.

Tagline: **"An AI colorist that measures before it grades."**

Core discipline: **measure, decide, apply, verify.** No agent judges color from a thumbnail impression. Every decision is driven by numbers pulled off the actual frames, and every grade must pass numeric QC gates before it ships.

Honest product description: **ffmpeg-based local media processing with Python, orchestrated by Claude agents.** "ffmpeg-only" means: no NLE integration of any kind (no Resolve scripting, no CDL/EDL interchange, no conform, no MCP pairing). The FAQ answers the inevitable question in one line: for Resolve automation use `samuelgursky/davinci-resolve-mcp`; our `.cube` files load anywhere `.cube` loads.

**Data locality (replacing v1's contradictory "local only" claim):** all pixel processing (decode, measure, grade, encode) runs locally. However, stills or thumbnails that agents inspect visually are sent to the configured model provider, as is derived numeric data in prompts. Therefore: the `qc` workflow has a fully local path (measurements and gates only, no frames leave the process); any workflow step that would transmit a frame requires explicit opt-in the first time per session; the README lists every artifact class that can leave the machine (selected stills, thumbnails, measurement JSON, file paths); temp files are created under a session directory and deleted on completion.

Market positioning claims are dated and scoped: per our 2026-07-19 sweep, no public Claude skill or Resolve MCP we found closes a measurement-driven grade loop; `meodai/skill.color-expert` (528 stars) covers design/web color with no motion-picture content. Stated as dated findings, not absolutes.

Audience: editors and filmmakers without a colorist, colorists who want a numeric second pair of eyes, Claude Code users grading their own content.

Repo copy is American English.

## 2. Product surface

Four workflows:

| Workflow | What it does | Renders? | Frames leave machine? |
|---|---|---|---|
| `qc` | Measure an existing export, run gates, emit report card | No | Never (fully local path) |
| `consistency` | Normalize WB/exposure across cuts; no look change | Yes | Only on opt-in |
| `grade` | Full loop: read, normalize, propose look, apply, gate, iterate | Yes | Only on opt-in |
| `advise` | Knowledge-only diagnosis from measurements plus stills | No | Stills on opt-in |

**Cost tiers** (config, disclosed in README): `quick` (single pass, no council, no variants, iteration cap 1), `standard` (cap 3), `deep` (multi-variant with council scoring, cap 3).

**Termination contract:** every iteration renders from the ORIGINAL decoded source with cumulative parameters; no iteration ever re-grades a previous delivery encode. Iteration cap per tier; a changed look-intent waiver consumes an iteration. On cap with failing gates: no deliverable is emitted; the run ends in `FAIL` with a report (which gates failed, by how much, what was tried) and the best candidate's parameters preserved in the manifest; the user may explicitly request a diagnostic render of a failing candidate, labeled as such.

**Run states:** every run terminates in exactly one of `PASS`, `FAIL`, `INDETERMINATE` (insufficient evidence coverage for the workflow's required gates: e.g. a landscape with no neutrals and no skin cannot PASS `consistency`; it reports what could not be evaluated), or `ERROR` (processing invariant violated: NaN/inf in the float pipeline, decode failure, unexpected filtergraph negotiation). Minimum evidence coverage per workflow is defined in the gate schema; vacuous passes are structurally impossible.

## 3. Architecture

### 3.1 The five agents (faithful to the video's five masteries)

Prompt files in `agents/`, dispatched by SKILL.md as subagents. Portability claim is scoped honestly: tested and supported on Claude Code; the SKILL.md plus references degrade to advisory use in other agent-skill hosts; a startup preflight checks shell, ffmpeg, Python version, vision availability, and subagent dispatch, and each missing capability fails closed with a named message (every agent gets a degradation rule, not just industry-standards).

1. **`color-theory`** (video: "advanced color theory, correction technique, color management"). Owns the color-management pipeline of section 4: encoding identification support, input/output transform generation via `colour-science`, correction-LUT compilation, LUT semantics. Inner loop: identify, transform, verify against reference vectors numerically.
2. **`industry-standards`** (video: "stay up to date"). Live-research agent; never answers from memory; no-web-tools branch declines rather than degrades silently. Inner loop: question, live search, cross-verify 2+ sources, dated cited brief.
3. **`cinematography`** (video: "cinematography and lighting"). Reads the shot: key direction, lighting ratio, source temps, mixed-light contamination, exposure placement, baked-in versus fixable. Structural reads may come from looking (opt-in still transmission); color conclusions must come from measured numbers. Inner loop: observe, hypothesize, test hypothesis against measurements, report.
4. **`detail-qc`** (video: "a keen eye for detail"). Gatekeeper: owns measurement methodology, gate schemas, run states. Pass/fail with exact numbers. Reports engineer units (RGB deltas in stated domain) plus colorist units (CCT/Duv, delta E 2000) only when their prerequisites hold (section 5.4).
5. **`look-design`** (video: "artistic vision"). Proposes look directions from a brief or reference stills (inspiration, not matching), builds looks as parameter stacks compiled into the look LUT, renders variants, submits to `detail-qc`; may override soft gates only via recorded waiver. Inner loop: propose, render, score (council in `deep`), refine.

### 3.2 Orchestration

`measure.py` runs first; `cinematography` and `color-theory` interpret; solvers compute; `grade.py` renders per-shot segments; `verify.py` gates; iterate within the termination contract. Agents choose intent and targets; deterministic solvers compute all numbers a closed form can produce (WB gains from neutral medians, exposure from luma targets, saturation trims from measured bands). Agents never hand-tune values a solver can compute.

## 4. The color pipeline

### 4.1 Working space and transforms

- **Working space: scene-linear Rec.709 primaries, D65** (named, versioned; ACEScg considered and deferred to keep v1 transforms minimal; revisit post-launch).
- **Input transforms (IDT):** per supported (curve, gamut) PAIR, not curve names alone: S-Log3/S-Gamut3.Cine, LogC3(EI800)/ARRI WideGamut3, LogC4/ARRI WideGamut4, V-Log/V-Gamut, C-Log3/Cinema Gamut, Rec.709 (BT.1886 decode), sRGB. Generated as versioned 1D shaper + 3D LUT pairs from `colour-science` at build time, shipped in-repo with generation scripts and manufacturer-vector tests (black, 18% grey, 90% white, primaries, over-range).
- **Corrections** (defined algebra, section 4.2) apply in scene-linear working space.
- **Look** applies after corrections, in a defined log-like grading space (shaper into quasi-log, look 3D LUT, shaper out), because creative contrast curves are authored against log-like axes.
- **Output transform (ODT):** named Rec.709/BT.1886 display transform, then explicit encode to the delivery profile.

### 4.2 Correction algebra (single source of truth, `corrections.py`)

Each correction is an equation with a named domain, pivot, and clipping policy:

| Correction | Definition | Domain |
|---|---|---|
| White balance | per-channel gains (gR, gG, gB) mapping the sampled neutral median to equal RGB of identical Rec.709 luma (amended 2026-07-19: v1's extra normalization by the weighted mean of the gains was not luma-preserving, measured -6.68% on a [0.3, 0.2, 0.1] neutral, and is removed) | scene-linear |
| Exposure | scalar multiplier 2^EV | scene-linear |
| Contrast | pivoted power/S-curve around stated pivot (18% grey in grading space) | grading space |
| Saturation | lerp toward luma axis, Rec.709 luma weights, stated | grading space (amended 2026-07-19: implementation applies it after contrast in grading space per the fixed order; the original scene-linear row contradicted the order column) |

Order is FIXED and non-commutative by design: IDT, WB, exposure, (to grading space) contrast, saturation, look, (from grading space) ODT. Non-commutativity tests deliberately swap adjacent stages and must fail.

Grading-space shaper (amended 2026-07-19): the shaper is invertible by construction, a C1-continuous affine toe below scene-linear 2^-7 joined to a log2 segment above it, spanning 0.001 to 1024.0. v1's pure-log2 shaper clipped everything at or below 0.001 to grading zero and inverted that to 0.001, so a no-op correction lifted display code black to 0.056234; the toe removes that. The 1024.0 ceiling is chosen so no supported camera curve clips: the largest working-space value any supported IDT produces over the code cube is 889.41 (LogC4/AWG4). Note that the ceiling sets the log axis scale, so a given `contrast` value is not comparable across this change; only the identity value 1.0 is unaffected, and no shipped workflow solves for contrast.

**Compilation:** the entire per-shot stack (WB, exposure, contrast, saturation) plus the global look compiles into ONE per-shot 3D LUT (65-point, plus 1D shaper handling domain), generated by `corrections.py`. The manifest records the parameters (the source of truth), and the LUT is their deterministic compilation, so reproducibility is parameter-level, not artifact-level.

### 4.3 The ffmpeg graph (empirically grounded)

Verified on this machine (ffmpeg 8.1.2): a `format=gbrp,...,eq,curves` graph auto-inserts yuv444p AND packed 8-bit rgb24 conversions. Therefore `eq`, `curves`, and every auto-negotiating filter are BANNED from the core path. The only pixel-touching filters in the render graph are:

```
decode -> scale (sws, explicit flags: in_range/out_range, in_color_matrix/out_color_matrix)
       -> format=gbrpf32le
       -> lut3d (IDT, interp=tetrahedral)
       -> lut3d (per-shot correction+look LUT, interp=tetrahedral)
       -> scale (sws, explicit out flags) -> format=<delivery pix_fmt> -> encode

(Amended 2026-07-19 during the feasibility spike: zscale was the original choice, but current
homebrew-core ffmpeg is a slim build without libzimg, so requiring zscale would
break the default install for most users. The graph needs only range and matrix
conversion at its edges; transfer and primaries conversion is the LUTs' job by
design. Explicit-flag swscale provides the same explicit-at-every-edge contract
on every ffmpeg build; the identity and agreement tolerances remain the
empirical arbiter of conversion precision.)
```

CI dumps the negotiated graph (`-v verbose`) and FAILS if any conversion appears that the spec did not place there explicitly. All internal math is float (gbrpf32le); quantization happens exactly once, at delivery encode.

### 4.4 Per-shot rendering replaces sendcmd

v1 renders each shot as its own segment (exact frame ranges from the cut list, PTS-exact trim), each to a lossless mezzanine (ffv1 in mkv, gbrp16le RGB: measured 2026-07-19, a YUV10 mezzanine costs a 0.061 max-error range bias on round-trip while RGB16 costs 0.00056, so RGB to YUV happens exactly once at delivery encode), then concatenates mezzanines and encodes the delivery file once. This removes runtime-command timing, boundary-flash risk, and per-filter command coverage from the design entirely. `sendcmd` is recorded as a rejected alternative (reason: command timing at cut boundaries and the eq YUV domain made Python-reference equivalence unprovable; EP4 used it successfully only because that pipeline was tuned end-to-end empirically rather than reference-matched).

### 4.5 Shot boundaries

Shot boundaries are a versioned input artifact. An explicit frame-based cut list (CSV) is the authoritative path. `scdet`-based auto-detection is a convenience that produces a PROPOSED cut list with per-cut confidence, stated threshold and hysteresis, minimum-shot-duration rule, and dissolve/fade quarantine (transition regions are excluded from measurement and correction blending in v1); the user (or the orchestrator, with the proposal shown) confirms it. Frame indices convert to timestamps via actual per-frame PTS, never nominal FPS. Test fixtures include CFR, VFR, B-frame reordering, nonzero start PTS, flashes, whip pans, dissolves, and similar-composition cuts.

### 4.6 Range and tag discipline

Range and matrix are declared explicitly at every graph edge (sws scale flags), and transfer/primaries are fixed by the named IDT/ODT LUTs, never inherited from tags alone. Input tags are treated as evidence; when absent or contradicted by decoded sample statistics, the user is asked. `verify.py` decodes the DELIVERED file and checks: bit-depth-scaled Y/Cb/Cr sample extrema against the declared range, plus `color_range`, `color_space`, `color_transfer`, `color_primaries` metadata. Fixtures: full-as-limited, limited-as-full, double squeeze, double expand, legal overshoot, correct-pixels-wrong-tags.

## 5. Measurement and gates

### 5.1 Evidence model

Every measurement is defined mathematically in the spec's gate schema: color domain, mask definition (neutral mask: low-chroma criterion in stated units; skin mask: hue/chroma band in stated space), spatial support, temporal sampling rule, outlier rejection, and minimum sample count. Absent evidence yields null, never a fabricated value. **ROIs and masks are computed once on the SOURCE and frozen**; every variant and every verification pass re-measures the same frozen regions (this closes the gate exploit where a bad correction pushes pixels out of a re-computed mask and the gate silently skips). A separate check asks whether frozen ROIs remain valid (e.g. still low-chroma enough to be neutral candidates) and reports if not. **Neutral evidence is reported per connected region, never only pooled** (measured 2026-07-19 on a real grade: a warm marble wall at R-B +7 and a cool shirt at R-B -13 pooled to +1, a false pass; a pooled summary exists only when region medians agree within a stated spread). Mask debug output includes a human-viewable contact sheet of the sampled regions, because unverified masks measure the set instead of the subject (three contaminated patches caught visually the same day).

### 5.2 Per-shot sampling

Stated sampling positions (25/50/75% of shot duration), clean-frame rejection rules (transition quarantine, flash rejection via temporal luma spike), minimum independent span. Short-shot policy: below 3 clean frames, measure what exists, mark affected gates `INDETERMINATE` for that shot, and prohibit automatic correction of that shot without user approval. Mixed-illumination policy: multimodal neutral clusters or temporal WB drift beyond threshold cause the tool to REFUSE a global WB for that shot, report the clusters, and route to the limitation (v1 has no secondaries); averaging incompatible evidence is prohibited.

### 5.3 Gate schema

Every gate ships as YAML with: signal domain (explicit: full-range RGB medians in 8-bit scale on frozen neutral masks, etc.), transfer/matrix context, statistic, threshold, hard/soft class, rationale, and validation status. Hard gates (never overridable): processing invariants are `ERROR` not gates (NaN/inf aborts); delivery-illegal sample ranges; output tag mismatch; grade-INTRODUCED clipping beyond threshold (measured source-relative, so baked-in camera clipping is reported but not blamed on the grade). Soft gates (waiver-able, recorded): the EP4-derived defaults, now with explicit domains, labeled **unvalidated defaults: on 2026-07-19 a pooled-mask evaluation both passed a grade carrying real per-object casts and would have failed a human grade the author approves (shadow floor and highlight ceiling encode one episode's contrast taste); they ship as opt-in examples with per-region evidence mandatory, pending corpus validation** (validation roadmap in README; presets: interview, documentary, night, commercial, music-video). Added gates: source-relative regression (delta E on frozen ROIs vs intent), temporal consistency across cut boundaries.

### 5.4 Colorist units

CCT/Duv and delta E 2000 are emitted only when prerequisites hold (valid transform to XYZ via the identified encoding, stated reference white D65, stated adaptation); otherwise the report shows RGB-domain numbers only and says why.

## 6. Encoding identification

Standard ffprobe transfer/primaries tags cannot uniquely identify camera log (curve, gamut) pairs, and real files frequently carry absent, generic, or transcode-inherited tags. The ladder is therefore:

1. **Metadata as evidence:** ffprobe tags plus container hints are collected and shown, never silently trusted as success.
2. **Explicit user selection** from the supported list is REQUIRED for any log-suspected media (low-contrast statistics or user assertion). Rec.709/sRGB display-referred media may proceed on tags plus sample-statistics sanity checks.
3. Statistical heuristics only ever produce a labeled SUGGESTION shown alongside the selection prompt; no numeric confidence figure is published until calibrated on a labeled corpus (roadmap).

v1 ingest matrix (README table): supported (curve, gamut) pairs of section 4.1; containers mp4/mov/mxf; codecs H.264 8-bit, HEVC 10-bit, ProRes; CFR and VFR. Everything else: honest refusal naming the matrix. Rec.709 and sRGB are distinct entries, never conflated.

## 7. Knowledge base

26 files per v1's coverage list, unchanged in scope, with an evidence framework: every factual claim carries an evidence tag: [S] standard (ITU/IEC/SMPTE), [M] manufacturer document, [E] our own empirical measurement (command and output recorded), [C] craft consensus (named practitioner sources; permitted in look-design and cinematography files where primary standards do not exist). Citation format: title, URL, version/date, retrieval date; citation URLs are resolution-checked locally before a file ships (the canary already caught one stale manufacturer URL). Files ship only after a different-family fact review of [S]/[M]/[E] claims; review date recorded in frontmatter. INDEX.md for progressive disclosure. Content policy: original prose, no book excerpts, no third-party LUTs.

Research pipeline: an agent locates primary documents and drafts honestly; a local fetch plus pdftotext fills gaps its fetcher cannot reach (403s, image-embedded formulas); every numeric constant is cross-checked against `colour-science`'s implementations; a human editorial pass is last.

## 8. Testing

Environment: Python >=3.11 (colour-science 0.4.7 requires >=3.11,<3.15; verified 2026-07-19), pinned NumPy 2.x and colour-science versions; ffmpeg minimum version pinned with a startup capability assertion (required filters: scale, format, lut3d with tetrahedral interp, scdet, plus the ffv1 encoder; CI fails if absent); CI matrix ubuntu + macos with the SAME pinned ffmpeg major version, negotiated-graph dump asserted on both.

Test classes with NUMERIC tolerances stated in-spec before coding:

1. **Transform vectors:** per (curve, gamut) pair, manufacturer-published vectors (18% grey, black, white, primaries, over-range) through IDT: max delta E 2000 <= 0.5 in working space; independent vectors from manufacturer docs, NOT generated by colour-science (no circular oracle); colour-science is the implementation, manufacturer PDFs are the oracle.
2. **LUT semantics:** .cube dialect pinned (Resolve/Iridas style, DOMAIN_MIN/MAX explicit, R-fastest ordering, 6-decimal precision, out-of-domain clamp stated); Python applies with explicit tetrahedral interpolation to match ffmpeg lut3d; identity and channel-permutation hand-authored cubes; Python-vs-ffmpeg application agreement on random float frames: max channel error <= 2/1023 (10-bit LSB x2 budget: interpolation grid + float-to-file rounding).
3. **Seeded gates:** every gate catches a synthetic violation and passes clean input; INDETERMINATE fixtures (no-neutral, no-skin, short-shot) must yield INDETERMINATE, not PASS.
4. **Boundary exactness:** per-shot segment rendering on fixtures (CFR, VFR, B-frames, nonzero start PTS): frame-hash equality at every boundary frame vs single-pass reference.
5. **Range/tag fixtures:** the six cases of section 4.6, verified on the DECODED delivered file.
6. **End-to-end smoke:** one audited openly-licensed clip (exact asset chosen and license-audited before inclusion) through `consistency`: PASS with report.
7. **Visual regression floor:** a small human-reviewed still set on release candidates only (banding, contouring, cut flashes); numeric gates are the product, but releases get eyeballs too (maintainer QC, consistent with the "verify generated media" rule).

## 9. Deliverable contract

Named output profiles in `presets/delivery/*.yaml`: v1 ships `h264-yt-sdr` (mp4, libx264, yuv420p, 8-bit, limited range, BT.709 matrix/transfer/primaries tags, CRF+maxrate stated, faststart) and `prores-422hq` (mov, limited-range handling stated). Profile defines: container, codec, pix_fmt, bit depth, range, all four color tags, rate control, audio policy (copy by default), timecode preservation, overwrite safety (never overwrite input; output naming scheme). Unsupported input/output combinations are refused by name. Mezzanine format: ffv1/mkv gbrp16le RGB (see 4.4), deleted on success, kept on FAIL for diagnosis.

## 10. Non-goals for v1

Unchanged from v1 (no NLE integration, no secondaries, no HDR, no third-party LUTs, no pixel-accurate reference matching, no denoise, no PyPI), plus per review: no auto-detected shot boundaries as authoritative (proposal only), no published heuristic confidence figures until calibrated, no claim of tested portability beyond Claude Code, no sendcmd path.

## 11. Repo layout, licensing, distribution

Layout as v1, plus `presets/delivery/`, `luts/idt/` (generated, versioned), and a licensing matrix in README: code including SKILL.md, agent prompts, presets, tests = MIT with SPDX headers; `references/` prose = CC-BY-4.0 (attribution format stated); generated LUTs and reports = MIT; bundled clip = its own audited license, attributed exactly; per-file SPDX identifiers throughout. Install: clone into `~/.claude/skills/colorist/`; optional agents copy; plugin packaging roadmap. README: before/after, one-command demo (the CLI decision is hereby made: yes, `python -m colorist qc <file>` ships in v1, since `qc`'s fully-local path requires a non-agent entry anyway), the `qc` wedge, LIMITS.md, credits.

## 12. Build process

As v1 (staged implementation, independent review before each stage lands, and an explicit human approval gate before anything is published), with one addition: implementation starts with a **P0 feasibility spike**: build the section 4.3 graph and the LUT compiler skeleton, run test classes 1, 2, and 4 on synthetic input, and prove the negotiated-graph assertion works in CI, BEFORE any other code. If the spike fails tolerances, the spec returns for revision rather than the code absorbing hacks.

## 13. Open questions

1. Demo/smoke clip: exact asset + license audit (decide before the spike completes).
2. ACEScg as working space: revisit after launch with real-world evidence.
