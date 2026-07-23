# SPDX-License-Identifier: MIT
"""Offline structural checks on the citation ledger.

These tests do not touch the network. They assert that the ledger and the
reference prose cannot drift apart: every evidence tag in use is either backed by
a verified ledger entry or named in the ledger's own list of unverified tags, and
every ledger entry is well formed and still in use.

The network-dependent half of the discipline lives in tools/verify_citations.py,
which re-resolves DOI locators against their registrar and is run by hand.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).parents[1]
REFERENCES = ROOT / "references"
LEDGER_PATH = REFERENCES / "CITATIONS.yaml"

#: [E:] is excluded on purpose. It marks a measurement or artifact produced by
#: this repository, which is verified by being reproducible here rather than by
#: an external locator.
TAG_PATTERN = re.compile(r"\[([SMC]): ([^\]]+)\]")

VALID_METHODS = {
    "registrar_metadata",
    "publisher_landing",
    "repository_anchor",
    "unverified",
}
VALID_CLAIM_DEPTHS = {"identifier_only", "content_checked"}
VALID_LOCATOR_TYPES = {"doi", "url", "repository"}


@pytest.fixture(scope="module")
def ledger() -> dict:
    return yaml.safe_load(LEDGER_PATH.read_text(encoding="utf-8"))


def _tags_in_prose() -> set[str]:
    """Return every ``KIND: text`` evidence tag used in reference markdown."""
    found: set[str] = set()
    for path in REFERENCES.rglob("*.md"):
        for match in TAG_PATTERN.finditer(path.read_text(encoding="utf-8")):
            found.add(f"{match.group(1)}: {match.group(2)}")
    return found


def _accounted_tags(ledger: dict) -> tuple[set[str], set[str]]:
    """Return ``(verified_tags, pending_tags)`` declared by the ledger."""
    verified = {
        tag for entry in ledger["citations"] for tag in entry.get("tags", [])
    }
    pending = {entry["tag"] for entry in ledger.get("pending_backfill", [])}
    return verified, pending


def test_ledger_declares_its_schema(ledger: dict) -> None:
    assert ledger["schema"] == "colorist/citations/v1"


def test_every_tag_in_use_is_accounted_for(ledger: dict) -> None:
    """A citation cannot enter the repository without a ledger decision."""
    legend = set(ledger["legend_tags"])
    verified, pending = _accounted_tags(ledger)
    unaccounted = sorted(_tags_in_prose() - legend - verified - pending)
    assert not unaccounted, (
        "these evidence tags appear in references/ but are in neither the "
        "citations list nor pending_backfill. Verify them, or record them as "
        f"pending with a reason: {unaccounted}"
    )


def test_no_tag_is_both_verified_and_pending(ledger: dict) -> None:
    verified, pending = _accounted_tags(ledger)
    both = sorted(verified & pending)
    assert not both, f"tags claimed as verified and pending at once: {both}"


def test_no_ledger_tag_is_stale(ledger: dict) -> None:
    """The ledger must not carry entries for tags nobody uses any more."""
    in_prose = _tags_in_prose()
    verified, pending = _accounted_tags(ledger)
    stale = sorted((verified | pending) - in_prose)
    assert not stale, (
        f"the ledger accounts for tags that no reference file uses: {stale}"
    )


def test_legend_tags_are_actually_legend_entries(ledger: dict) -> None:
    """The legend exemption must not be used to smuggle a real citation past."""
    for tag in ledger["legend_tags"]:
        body = tag.split(": ", 1)[1]
        assert body == "..." or body.islower() or body.startswith("manufacturer"), (
            f"legend exemption {tag!r} looks like a real citation, not a legend entry"
        )


def test_citation_ids_are_unique(ledger: dict) -> None:
    ids = [entry["id"] for entry in ledger["citations"]]
    duplicates = sorted({entry for entry in ids if ids.count(entry) > 1})
    assert not duplicates, f"duplicate citation ids: {duplicates}"


@pytest.mark.parametrize("field", ["id", "kind", "title", "locator", "verification"])
def test_every_citation_has_required_fields(ledger: dict, field: str) -> None:
    missing = [
        entry.get("id", "<no id>")
        for entry in ledger["citations"]
        if field not in entry
    ]
    assert not missing, f"citations missing {field!r}: {missing}"


def test_locators_are_well_formed(ledger: dict) -> None:
    for entry in ledger["citations"]:
        locator = entry["locator"]
        assert locator["type"] in VALID_LOCATOR_TYPES, (
            f"{entry['id']} has unknown locator type {locator['type']!r}"
        )
        assert locator.get("value"), f"{entry['id']} has an empty locator value"
        if locator["type"] == "doi":
            assert locator["value"].startswith("10."), (
                f"{entry['id']} locator {locator['value']!r} is not a DOI"
            )
        if locator["type"] == "repository":
            assert (ROOT / locator["value"]).exists(), (
                f"{entry['id']} points at a repository path that does not exist: "
                f"{locator['value']}"
            )


def test_verification_records_are_well_formed(ledger: dict) -> None:
    for entry in ledger["citations"]:
        verification = entry["verification"]
        assert verification["method"] in VALID_METHODS, (
            f"{entry['id']} has unknown verification method "
            f"{verification['method']!r}"
        )
        assert verification["claim_depth"] in VALID_CLAIM_DEPTHS, (
            f"{entry['id']} has unknown claim_depth {verification['claim_depth']!r}"
        )
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(verification["checked"])), (
            f"{entry['id']} has no ISO date in its checked field"
        )


def test_content_checked_requires_stated_evidence(ledger: dict) -> None:
    """Claiming a document was read requires saying what was read."""
    for entry in ledger["citations"]:
        verification = entry["verification"]
        if verification["claim_depth"] == "content_checked":
            assert verification.get("detail"), (
                f"{entry['id']} claims content_checked without a detail field "
                "stating what was checked"
            )


def test_unverified_method_is_not_used_in_the_citations_list(ledger: dict) -> None:
    """An unverified source belongs in pending_backfill, not among the verified."""
    unverified = [
        entry["id"]
        for entry in ledger["citations"]
        if entry["verification"]["method"] == "unverified"
    ]
    assert not unverified, (
        f"these citations are unverified and belong in pending_backfill: {unverified}"
    )


def test_pending_entries_state_a_reason(ledger: dict) -> None:
    for entry in ledger.get("pending_backfill", []):
        assert entry.get("reason", "").strip(), (
            f"pending tag {entry['tag']!r} does not say why it is unverified"
        )


def test_rejected_locators_record_what_was_wrong(ledger: dict) -> None:
    for entry in ledger.get("rejected", []):
        for field in ("supplied", "claimed_as", "actually", "checked"):
            assert entry.get(field), (
                f"rejected locator {entry.get('supplied', '<unknown>')!r} is "
                f"missing {field!r}"
            )
