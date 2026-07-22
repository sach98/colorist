# Look Intent And Waivers

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Project guidance: use recorded waivers when a deliberate visual choice conflicts with a provisional soft gate. A waiver documents the decision; it does not make an unmeasured result safe.

The shipped soft gates cover white balance, shadow floor, highlight ceiling, and skin saturation [E: presets/gates/interview.yaml]. Pascarella demonstrates a milky-shadows treatment that can raise the shadow floor [C: Dante Pascarella, "5 Color Grading Secrets That Make Pro Filmmakers Stand Out"]. The project records waiver metadata for intentional soft-gate exceptions [E: src/colorist/gates.py].

The shipped hard gates cover decoded delivery range legality, delivery-tag match, and grade-introduced clipping [E: presets/gates/interview.yaml]. They are not waiverable in the project workflow. The current preset has no hard gamut-excursion gate.

Project guidance: use the waiver reason and scope to explain the intended deviation, then preserve delivery-range, tag, and introduced-clipping checks. A waiver is reviewable metadata, not a substitute for a creative reference or technical verification.
