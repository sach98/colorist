# SPDX-License-Identifier: MIT
"""Check every DOI locator in references/CITATIONS.yaml against its registrar.

Why this exists, in one sentence: a DOI that RESOLVES is not a DOI that is the
work you claimed, and the difference is not rare.

When the v2 research sweep was audited on 2026-07-23, six of eighteen supplied
DOIs were wrong. Five of those six resolved successfully to a real record that
was a DIFFERENT paper, because publisher DOI suffixes are near-sequential and a
single corrupted digit lands on a neighbour. An HTTP status check passes all
five. Only comparing the registrar's title against the claimed title catches
them, which is what this tool does.

This tool needs the network and is therefore NOT part of the test suite.
Run it by hand when adding or revising citations:

    .venv/bin/python tools/verify_citations.py references/CITATIONS.yaml

The offline structural companion is tests/test_citations.py, which asserts that
every evidence tag used in references/ is accounted for in the ledger.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml


USER_AGENT = "colorist-citation-check/1.0 (+https://github.com/sach98/colorist)"
#: Normalized title similarity at or above which a registrar record is accepted.
#: Chosen to absorb publisher markup and punctuation differences while still
#: rejecting a different paper. Every comparison prints its ratio, so a value
#: near the boundary is visible rather than silently accepted.
TITLE_MATCH_MIN = 0.85
_MARKUP = re.compile(r"<[^>]+>")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def _fetch_json(url: str) -> dict | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    try:
        # Crossref embeds JATS abstracts containing raw control characters.
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        return None


def crossref_record(doi: str) -> dict | None:
    payload = _fetch_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")
    if not payload or payload.get("status") != "ok":
        return None
    message = payload["message"]
    authors = message.get("author") or []
    issued = message.get("issued", {}).get("date-parts", [[None]])[0]
    return {
        "registrar": "Crossref",
        "title": (message.get("title") or [""])[0],
        "first_author": authors[0].get("family", "") if authors else "",
        "year": issued[0] if issued else None,
        "venue": (message.get("container-title") or [""])[0],
    }


def datacite_record(doi: str) -> dict | None:
    payload = _fetch_json(f"https://api.datacite.org/dois/{urllib.parse.quote(doi)}")
    if not payload or "data" not in payload:
        return None
    attributes = payload["data"]["attributes"]
    creators = attributes.get("creators") or [{}]
    publisher = attributes.get("publisher")
    return {
        "registrar": "DataCite",
        "title": (attributes.get("titles") or [{}])[0].get("title", ""),
        "first_author": creators[0].get("familyName") or creators[0].get("name", ""),
        "year": attributes.get("publicationYear"),
        "venue": publisher.get("name") if isinstance(publisher, dict) else (publisher or ""),
    }


def normalize_title(title: str) -> str:
    """Strip publisher markup and punctuation so titles compare on words alone."""
    return " ".join(_NON_ALNUM.sub(" ", _MARKUP.sub("", title).lower()).split())


def check_entry(entry: dict) -> tuple[str, str]:
    """Return ``(verdict, detail)`` for one ledger entry's DOI locator."""
    locator = entry.get("locator", {})
    if locator.get("type") != "doi":
        return "SKIPPED", f"locator type {locator.get('type')!r} is not machine checkable here"

    doi = locator["value"]
    record = crossref_record(doi) or datacite_record(doi)
    if record is None:
        return "UNRESOLVED", f"{doi} is not known to Crossref or DataCite"

    claimed = normalize_title(entry["title"])
    found = normalize_title(record["title"])
    ratio = difflib.SequenceMatcher(None, claimed, found).ratio()
    summary = (
        f"{record['registrar']} says: {record['title']!r} "
        f"({record['first_author']} {record['year']}, {record['venue']}) "
        f"[title similarity {ratio:.3f}]"
    )
    if ratio < TITLE_MATCH_MIN:
        return "MISMATCH", summary
    return "VERIFIED", summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ledger", type=Path, help="path to CITATIONS.yaml")
    args = parser.parse_args(argv)

    ledger = yaml.safe_load(args.ledger.read_text(encoding="utf-8"))
    entries = [e for e in ledger.get("citations", []) if e.get("locator", {}).get("type") == "doi"]

    tally: dict[str, int] = {}
    for entry in entries:
        verdict, detail = check_entry(entry)
        tally[verdict] = tally.get(verdict, 0) + 1
        print(f"{verdict:<11} {entry['id']}\n            {detail}")

    print("\n" + ", ".join(f"{count} {verdict}" for verdict, count in sorted(tally.items())))
    failures = tally.get("MISMATCH", 0) + tally.get("UNRESOLVED", 0)
    if failures:
        print(f"\n{failures} DOI locator(s) did not verify. Fix the ledger before citing them.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
