# Building A Look Stack

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Operation order changes the result, so the project defines one explicit path rather than a universal node-tree rule. Darren Mostyn and Dante Pascarella each demonstrate color management and primary corrections before their creative look, while using different node layouts [C: Darren Mostyn, "How I Grade this Ad" masterclass] [C: Dante Pascarella, "5 Color Grading Secrets That Make Pro Filmmakers Stand Out"].

The repository path decodes to working scene-linear RGB, applies white balance and exposure, shapes into grading space for contrast and saturation, applies the optional look, then output-encodes [E: src/colorist/corrections.py, compile_shot_lut]. Project guidance: evaluate the active look while making upstream corrections, because a non-linear look can change the visible result [C: Darren Mostyn, "How I Grade this Ad" masterclass].

Mostyn places some effects after a Rec.709 transform, while Pascarella places a LUT at the end of his demonstrated tree [C: Darren Mostyn, "How I Grade this Ad" masterclass] [C: Dante Pascarella, "5 Color Grading Secrets That Make Pro Filmmakers Stand Out"]. These placements are not generally topologically identical: non-linear transforms need not commute. This repository's fixed placement is the one its tests verify.

This repository does not implement denoise or texture finishing, so it makes no verified claim about their universal placement [E: repository LIMITS.md]. Project guidance: determine denoise order from the chosen tool, source condition, and delivery requirement, then evaluate the result before committing it.

The project's saturation operator is the stated Rec.709-luma interpolation in grading space [E: src/colorist/corrections.py, _saturate]. Pascarella demonstrates a distinct HSV S-channel workflow [C: Dante Pascarella, "5 Color Grading Secrets That Make Pro Filmmakers Stand Out"]. It is a different operator with different behavior; the v1 repository does not claim to implement it.
