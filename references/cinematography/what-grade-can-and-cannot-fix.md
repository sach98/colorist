# What Grade Can And Cannot Fix

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Grading can reshape balance, contrast, and color, but it cannot reconstruct every lost or spatially specific detail. The practical boundary depends on the retained source, the defect, available tools, and the delivery requirement [E: repository LIMITS.md].

Clipped source highlights usually cannot reveal scene detail that was never recorded. A known wrong transform applied to retained source footage is different: it can be reprocessed. The operational risk is silent corruption, where the retained deliverable looks plausible but was transformed or tagged incorrectly. Project guidance: retain source material and verify the transformed delivery.

Severe underexposure, noise, missed focus, and baked motion blur can limit acceptable recovery. A specialized restoration workflow may improve some material, while sacrificing detail or introducing artifacts. This project does not implement denoise, deblur, focus recovery, or spatial secondaries [E: repository LIMITS.md].

Mixed-light scenes may have more than one legitimate neutral. A single global balance can improve one region while making another worse [C: Flashpoint Lighting, "Color Temperature in Lighting"] [E: src/colorist/measure.py, multimodal neutral refusal]. Project guidance: use a secondary-capable workflow when the intended correction is local; this project's global correction path reports multimodal evidence instead.

When the needed information remains in the retained source, primary exposure, balance, contrast, and saturation adjustments can often improve a shot. The outcome still depends on noise, clipping, compression, illumination, and the intended look. Project guidance: verify the rendered delivery, not only the working image.
