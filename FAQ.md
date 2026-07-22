# FAQ

<!-- SPDX-License-Identifier: MIT -->

**Does this work with DaVinci Resolve?**
No, by design. This tool is ffmpeg-only: it grades end to end locally with no NLE integration. If you need Resolve automation, use samuelgursky/davinci-resolve-mcp. Our `.cube` look files load anywhere `.cube` loads, including Resolve.

**Why no CDL/EDL export?**
Scope honesty: a bag of CDL values without a conform story is not importable in practice, and building a real conform pipeline is NLE integration by another name. The per-shot corrections manifest (versioned JSON) plus the look `.cube` carry everything a colorist needs to port a grade by hand.

**The gates failed my footage but I like my grade. Is the tool broken?**
Probably neither. The shipped gate values encode one production's taste and are labeled unvalidated; a professional grade the author approves also fails some of them. v1 ships one gate preset, `interview`; put your intent on the record by pointing `--preset` at your own copy with adjusted values. A first-class per-run waiver record is on the roadmap, not a shipped CLI surface. If you believe a gate VALUE is wrong in general, that is exactly the feedback the project wants.

**Why did my run come back INDETERMINATE?**
Required evidence for a hard gate was absent: typically no usable neutral regions, neutral regions that disagree on a white axis, a delivery whose expected color tags or native range could not be verified, or grade-introduced clipping that could not be measured because no `--source-reference` was supplied. INDETERMINATE means the tool refused to fabricate a measurement or to call a hard gate PASS without evidence. The report says exactly what was missing.

**Why do I have to tell it which log curve I shot?**
Standard file metadata cannot express a vendor (curve, gamut) pair, and real files routinely carry absent or wrong tags. Guessing silently poisons everything downstream. So you declare the pair with `--encoding`; the tool does not detect it or suggest one, and it refuses an unsupported value by name. If your declaration conflicts with the file's own tags, the run stops and shows the conflict.

**Can it match my footage to a reference still from a film?**
No. Reference stills are treated as inspiration (palette, contrast character) for the look designer; pixel-accurate reference matching is a different product.

**HDR?**
Not in v1. SDR Rec.709 delivery only. HDR arrives via a researched delivery-spec update, not a guess.

**Does my footage get uploaded anywhere?**
No. All pixel processing is local ffmpeg. `qc` transmits nothing. Agent workflows ask before any still is shown to a model.
