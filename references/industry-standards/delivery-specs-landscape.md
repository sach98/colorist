# Delivery Specs Landscape

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Delivery requirements belong to the destination specification, not to a generic list. Project guidance: obtain the current written delivery specification from the broadcaster, platform, distributor, or client before mastering.

Rec.709 specifies SDR system colorimetry and its OETF; it does not by itself prescribe a 2.4 reference display gamma or a universal 100-nit delivery limit [S: ITU-R BT.709-6, identifier-cited]. BT.1886 and the applicable reference-viewing specification address display behavior separately [S: ITU-R BT.1886, identifier-cited] [S: ITU-R BT.2035, identifier-cited]. Acceptance limits are destination-specific.

HDR delivery requires an explicit transfer function, mastering metadata where required, colorimetry, range, codec, and destination acceptance criteria. Project guidance: do not infer a PQ peak level or a Rec.2020 mapping from an SDR delivery document.

Resolution, framing, bitrate, codec, audio loudness, captions, and packaging are all destination-specific. Project guidance: record the version and retrieval date of the supplied specification in the mastering job, and do not present a platform example as a universal requirement.

Project guidance: compare the job's dated specification with the final encode settings and delivery report. If the document is unavailable or ambiguous, request clarification from the destination rather than inventing numeric limits.
