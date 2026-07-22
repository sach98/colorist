# Reading A Shot

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Start by evaluating the captured image before changing it. Shadow direction, density, and practicals can suggest a lighting hypothesis, but they do not prove the original setup [C: Filmmakers Academy, "Cinematography Lighting Ratios"]. Project guidance: record the hypothesis, then compare it with the sequence and any available reference.

Evaluate motion, not only a still. Darren Mostyn demonstrates playing the clip before settling on a grade because the subject can move through the light [C: Darren Mostyn, "How I Grade this Ad" masterclass]. This project samples integer quarter, half, and three-quarter positions for shots of three or more frames; it does not claim those samples represent every frame [E: src/colorist/measure.py, sample_positions].

Project guidance: inspect scopes before and after a correction, and compare the enabled and bypassed result. Mostyn demonstrates waveform and skin sampling as part of that workflow [C: Darren Mostyn, "How I Grade this Ad" masterclass]. In this repository, camera code values decode to scene-linear working RGB; white balance and exposure run there, then contrast and saturation run in the log2 grading space before the optional look and output encode [E: src/colorist/corrections.py, compile_shot_lut].
