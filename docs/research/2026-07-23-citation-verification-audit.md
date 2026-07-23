# Citation verification audit, 2026-07-23

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

A record of what happened when an AI research sweep's citations were checked
against their registrars, and why this project's verification method changed as a
result. Every number here is reproducible with
`tools/verify_citations.py`.

## What was run

Three literature-location sweeps were run through a delegated agent, covering
skin colour and vectorscope skin-line provenance, keying and matte refinement,
and uniform colour spaces with ACES structure. Each prompt required a checkable
locator per claim, explicitly permitted the answer "NONE FOUND", and stated that
a fabricated locator was worse than no answer. The sweeps returned 18 DOIs.

Each DOI was resolved against Crossref, with DataCite as a fallback for datasets,
and the registrar's title was compared against the title the sweep claimed for it.

## Result

| Outcome | Count |
|---|---|
| DOI resolves and is the claimed work | 12 |
| DOI resolves but is a **different** work | 5 |
| DOI does not resolve at all | 1 |
| **Total** | **18** |

Six of eighteen locators, one third, were wrong.

## The finding that changed the method

**Five of the six failures resolve cleanly.** They return HTTP 200, they land on
a real record at a real publisher, and they would pass any check based on status
codes or on whether a link is dead. They are wrong because they point at a
different paper.

The mechanism is that publisher DOI suffixes are near-sequential, so a single
corrupted digit lands on a neighbouring article in the same journal:

| Supplied | Claimed to be | Actually is | Correct locator |
|---|---|---|---|
| `10.1002/col.5080200106` | Hung and Berns 1995, constant hue loci | Rich 1995, observer metamerism | `10.1002/col.5080200506` |
| `10.1002/col.10049` | CIEDE2000 development paper | Barnard 2002, a colour data set | `10.1002/col.1049` |
| `10.1145/237170.237275` | Smith and Blinn, Blue screen matting | Nishimura 1996, VC-1 | `10.1145/237170.237263` |
| `10.1364/JOSAA.23.002077` | ellipsoidal keys in uniform spaces | Huertas 2006, an OSA-UCS colour-difference formula | none located |
| `10.1109/TPAMI.2022.3165384` | Lin 2022, temporally stable video matting | does not resolve | `10.1109/wacv51458.2022.00319` |

The project's previous verification artifact,
`docs/ai/research-archive/url-check.txt`, is a list of URLs and their HTTP status
codes. It would have passed all five. It also contains two other defects visible
on inspection: several entries carry trailing punctuation that was captured into
the URL and produced spurious 404s, and several entries are
`vertexaisearch.cloud.google.com/grounding-api-redirect/...` links, which are
ephemeral search-grounding redirects rather than durable locators.

Status codes are not verification. Metadata comparison is.

## A second finding: the agent's own confidence signal carries no information

Each claim was requested with a self-label of DIRECTLY READ or SECONDHAND. Three
of the six wrong locators were labelled DIRECTLY READ, including the one that
does not resolve at all. The self-label was not used in this audit and should not
be used in future ones.

## What is not claimed here

This audit measured one thing: whether a supplied DOI is the work it was said to
be. It did not check whether any paper says what the sweep summarised it as
saying. Every entry now in `references/CITATIONS.yaml` is therefore recorded at
`claim_depth: identifier_only`, and content verification is a separate step taken
per claim as reference prose is written.

The sweeps were also genuinely productive, which is worth recording alongside the
error rate: twelve correct locators, including the two papers that most directly
serve this project's open questions, Zhao 2020 on hue linearity across uniform
colour spaces and Zeng and Luo 2011 on preferred skin colours and their
tolerances. The conclusion is not that delegated literature search is useless. It
is that its output is a set of candidates, and candidates are not citations until
a registrar agrees.

## Method now in force

1. Delegated sweeps produce candidate locators, treated as untrusted input.
2. `tools/verify_citations.py` resolves every DOI against Crossref or DataCite
   and compares normalised titles, printing the similarity ratio for each.
3. Anything below the stated similarity threshold, or unresolvable, is recorded
   in the `rejected` section of `references/CITATIONS.yaml` with what it was
   claimed to be and what it actually is, so the same wrong locator cannot be
   re-adopted later.
4. `tests/test_citations.py` runs offline on every suite run and fails if any
   evidence tag used in `references/` is neither backed by a verified ledger
   entry nor named in the ledger's list of tags still awaiting verification.
