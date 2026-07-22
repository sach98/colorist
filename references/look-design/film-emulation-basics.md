# Film Emulation Basics

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Film-emulation vocabulary can help describe a look, but no single recipe is a physically complete simulation of every stock, camera, laboratory, and projection path.

Halation is a term used for highlight glow associated with film capture and print behavior [C: Dehancer, "Film Documentation: Halation"]. Project guidance: use it as an aesthetic cue and test its amount against the intended reference rather than assuming a universal red-or-orange mechanism.

Film grain and digital sensor noise have different origins and visual behavior. Digital noise is stochastic and can depend on signal level, temperature, readout, and processing; it is not generally a uniform chromatic grid. Project guidance: match grain or noise by observed scale, chroma, movement, and tonal dependence, not by a claim of uniformity.

Gate weave is an aesthetic term for frame-position instability associated with film transport. Project guidance: treat any digital weave as a deliberate texture choice and verify that it supports the reference rather than distracting from the image.

Print density is often used as shorthand for a darker, more subtractive-looking color response. Project guidance: describe the intended curve and color relationship explicitly, then test it against a reference instead of promising a mathematically accurate film simulation.

This v1 project emulates none of these spatial or texture behaviors [E: repository LIMITS.md]. They remain vocabulary for communicating an intended look.
