# Exposure Placement

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Exposure placement is an acquisition decision that trades highlight headroom, shadow noise, and the intended display rendering. Log footage needs its declared camera transform before its code values can be compared meaningfully [E: tests/vectors manufacturer anchors and src/colorist/idt.py].

Waveform placement is a useful display-referred check, but there is no universal skin IRE target that guarantees a flattering or natural result. Project guidance: choose exposure from the scene, complexion, intended look, display transform, and headroom, then validate it over the shot instead of matching a generic number.

Project guidance: any deliberate overexposure strategy must preserve the camera's required highlight detail and document its offset for matching. It may improve a chosen capture tradeoff, but inconsistent offsets can make later shot matching more difficult.

Use the camera maker's documentation and the matching curve and gamut pair. The repository records Sony S-Log3 18% grey at CV 420, 41 IRE, and 90% white at CV 598, 61 IRE [M: Sony S-Gamut3.Cine/S-Log3 Technical Summary, tests/vectors/slog3_sgamut3cine.json]. Its LogC4 anchor is 18% scene-linear at LogC4 0.2784, not 32% [M: ARRI LogC4 Logarithmic Color Space Specification, tests/vectors/logc4_awg4.json].
