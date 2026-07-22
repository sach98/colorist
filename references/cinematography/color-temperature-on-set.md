# Color Temperature On Set

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Correlated color temperature, or CCT, describes an illuminant chromaticity relative to the blackbody locus. It does not define the illuminant's spectral power distribution: different spectra can share a CCT [S: CIE 15:2018, Colorimetry].

In production, 3200 K and 5600 K are useful nominal labels for tungsten-oriented and daylight-oriented setups. They are starting points, not spectral guarantees. Project guidance: set white balance from the actual key light or a measured neutral, then judge whether the chosen balance supports the scene.

Mixed illumination can leave different objects requiring different chromatic corrections. Project guidance: decide whether that difference is motivated and desirable, or control it on set before expecting one global white-balance correction to satisfy every region.

Color-correction gels are filters: they attenuate selected wavelength bands and reduce output. CTO commonly attenuates more blue relative to other wavelengths; CTB changes the relative transmission in the opposite direction. Project guidance: use the manufacturer's transmission data and test a camera or meter under the intended fixture. Fractional gels can move a source toward an ambient condition, but they cannot promise a perfect spectral or camera match.
