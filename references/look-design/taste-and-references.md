# Taste And References

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Project guidance: use reference stills and moving references to articulate a target, while recognizing that their viewing conditions, transforms, and source material may be unknown.

Project guidance: use waveform and vectorscope observations to describe black floor, highlight placement, hue relationships, and saturation in a reference. A scope reading is a diagnostic of the displayed reference, not proof of its original scene or transform [C: Frame.io, "For Colorists: Review and Reference"].

Mostyn demonstrates inspecting waveform and skin sampling, then checking a node enabled and bypassed [C: Darren Mostyn, "How I Grade this Ad" masterclass]. Project guidance: establish the source balance and intended viewing transform before pursuing a creative reference match, and verify each change against the approved target.

Mostyn advises playing the clip instead of grading only its first frame [C: Darren Mostyn, "How I Grade this Ad" masterclass]. This tool samples integer quarter, half, and three-quarter positions, but it does not implement clean-frame rejection [E: src/colorist/measure.py, sample_positions].

Mostyn and Pascarella demonstrate isolating skin while making broader creative changes [C: Darren Mostyn, "How I Grade this Ad" masterclass] [C: Dante Pascarella, "5 Color Grading Secrets That Make Pro Filmmakers Stand Out"]. A 3D LUT cannot perform spatial windows, tracking, blur, or matte cleanup [E: repository LIMITS.md]. Project guidance: use a secondary-capable workflow when the reference requires spatial isolation.
