# Feasibility spike: measured results

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Date: 2026-07-19
Machine: macOS (Darwin 25.5.0), ffmpeg 8.1.2 (homebrew-core slim build), Python 3.11.1, colour-science 0.4.7, numpy 2.4.6, scipy 1.17.1.

> The exact figures below are DATED OBSERVATIONS on that specific machine and
> ffmpeg build, recorded to show the architecture works and stays inside its
> stated tolerances. They are not build-invariant constants: a different ffmpeg
> build can produce a slightly different value (for example the Python-vs-ffmpeg
> LUT agreement measured about 0.00064 here and about 0.00046 on another 8.1.x
> build), and the tolerances, not the point values, are what the test suite
> enforces.

## Verdict: SPIKE PASS

The architecture described in `design.md` is implementable as specified, with the two measured amendments below, both already folded into that document. All 12 spike tests pass locally.

## Observed evidence

- Local pytest: `12 passed` (test_lut 5, test_ffgraph 2, test_render_identity 1, test_lut_agreement 1, test_idt 3).
- Banned-graph proof: `format=gbrp,eq,curves` negotiates `{gbrp, rgb24, yuv420p, yuv444p}` on ffmpeg 8.1.2; the assertion harness detects and rejects it.
- Clean-graph negotiated set: `{gbrpf32le, gbrp16le}` after the explicit conversions (plus source-native format before them).
- Python vs ffmpeg tetrahedral LUT agreement: max channel error `0.000642` vs tolerance `2/1023 = 0.001955`. No tetrahedron-ordering fix was needed.
- Identity render round-trip (RGB16 mezzanine): max error `<= 2/1023` (passing); measured bare round-trips during diagnosis: YUV10 mezzanine `0.0608` max error (range bias, rejected), RGB16 mezzanine `0.000565` (adopted).
- IDT vendor-vector tests: S-Log3 CV95 decodes to exactly 0.0, CV420 to exactly 0.18; LogC4 table anchors within 4-decimal rounding; through-the-LUT grey18 delta E 2000: S-Log3 `0.047`, LogC4 `0.052` (tolerance 0.5).
- Vendor provenance: both PDFs sha256-recorded; Sony fetched via Internet Archive snapshot of the official URL (direct URL serves 403 to non-browser clients, verified three ways).

## Amendments produced by the spike (already folded into the design)

1. zscale replaced with explicit-flag sws `scale` (homebrew-core ffmpeg ships without libzimg; adoption).
2. Mezzanine is ffv1 `gbrp16le` RGB (YUV10 leg measured 30x over tolerance; RGB to YUV exactly once at delivery).
3. scipy added to dependencies (colour-science CCT/Duv features).
4. Per-vector tolerances for rounded table anchors (S-Log3 white90 at 5e-3).

## Caveat

CI (.github/workflows/ci.yml) is authored and its assertions are the exact commands proven locally, but it cannot RUN until the repository is published, so these numbers are local observations only. The BtBN "latest" tag must be checked for ffmpeg major 8 on the first CI run and pinned to a specific release tag if it has moved.

## Consequence

The remaining work (the other IDTs, measurement, cut lists, gates, correction algebra, grade, verify, end to end, CLI, and the real-clip smoke test) proceeds on proven ground.
