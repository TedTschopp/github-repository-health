"""Parser for the normative Markdown control catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


CONTROL_HEADING = re.compile(r"^###\s+([A-Z]{3}-\d{2})\s+—\s+(.+?)\s*$")
FIELD = re.compile(r"^-\s+\*\*(.+?):\*\*\s*(.*)$")
STANDARD_VERSION = re.compile(r"\*\*Status:\*\*\s+Provisional\s+([^\s]+)")
SOURCE_ID = re.compile(r"SRC-\d{3}")
METRIC_ID = re.compile(r"M-[A-Z]{3}-[0-9A-Z]+")


@dataclass(frozen=True)
class Control:
    control_id: str
    title: str
    dimension: str
    gate: str | None
    tier_applicability: str
    requirement: str
    intent: str
    acceptable_patterns: str
    required_evidence: str
    measurement_ids: tuple[str, ...]
    threshold: str
    unknown_na_exception: str
    grade_effect: str
    minimum_assurance: str
    remediation: str
    owner_review_date: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    standard_version: str
    path: str
    controls: tuple[Control, ...]


def _plain_markdown(value: str) -> str:
    """Remove emphasis markers while retaining links and normative wording."""

    return value.replace("**", "").strip()


def parse_catalog(path: str | Path) -> Catalog:
    """Parse the versioned Markdown catalog into strongly named controls.

    The parser fails closed if a required catalog field is absent. This avoids
    silently assessing a partially edited standard as though it were complete.
    """

    catalog_path = Path(path).resolve()
    text = catalog_path.read_text(encoding="utf-8")
    version_match = STANDARD_VERSION.search(text)
    if not version_match:
        raise ValueError(f"Catalog does not declare a provisional version: {catalog_path}")

    parsed: list[Control] = []
    current_id: str | None = None
    current_title = ""
    current_fields: dict[str, str] = {}

    def finish() -> None:
        nonlocal current_id, current_title, current_fields
        if current_id is None:
            return
        aliases = {
            "tier/applicability": "tier_applicability",
            "normative statement": "requirement",
            "acceptable patterns/equivalents": "acceptable_patterns",
            "evidence/evidence minimum": "required_evidence",
            "linked measure": "linked_measure",
            "unknown/n-a/exception treatment": "unknown_na_exception",
            "grade effect": "grade_effect",
            "minimum assurance": "minimum_assurance",
            "owner/review date": "owner_review_date",
            "authoritative source": "authoritative_source",
        }
        normalized = {aliases.get(key.lower(), key.lower()): value for key, value in current_fields.items()}
        required = {
            "tier_applicability",
            "requirement",
            "intent",
            "acceptable_patterns",
            "required_evidence",
            "linked_measure",
            "threshold",
            "unknown_na_exception",
            "grade_effect",
            "minimum_assurance",
            "remediation",
            "owner_review_date",
            "authoritative_source",
        }
        missing = sorted(required - normalized.keys())
        if missing:
            raise ValueError(f"{current_id} is missing catalog fields: {', '.join(missing)}")
        assurance_match = re.search(r"\b(E[1-4])\b", normalized["minimum_assurance"])
        if not assurance_match:
            raise ValueError(f"{current_id} has no E1-E4 minimum assurance")
        gate_value = normalized.get("gate", "")
        gate_match = re.search(r"\b(G-0[1-4])\b", gate_value)
        parsed.append(
            Control(
                control_id=current_id,
                title=current_title,
                dimension=current_id.split("-", 1)[0],
                gate=gate_match.group(1) if gate_match else None,
                tier_applicability=_plain_markdown(normalized["tier_applicability"]),
                requirement=_plain_markdown(normalized["requirement"]),
                intent=_plain_markdown(normalized["intent"]),
                acceptable_patterns=_plain_markdown(normalized["acceptable_patterns"]),
                required_evidence=_plain_markdown(normalized["required_evidence"]),
                measurement_ids=tuple(dict.fromkeys(METRIC_ID.findall(normalized["linked_measure"]))),
                threshold=_plain_markdown(normalized["threshold"]),
                unknown_na_exception=_plain_markdown(normalized["unknown_na_exception"]),
                grade_effect=_plain_markdown(normalized["grade_effect"]),
                minimum_assurance=assurance_match.group(1),
                remediation=_plain_markdown(normalized["remediation"]),
                owner_review_date=_plain_markdown(normalized["owner_review_date"]),
                source_ids=tuple(dict.fromkeys(SOURCE_ID.findall(normalized["authoritative_source"]))),
            )
        )
        current_id = None
        current_title = ""
        current_fields = {}

    for raw_line in text.splitlines():
        heading = CONTROL_HEADING.match(raw_line)
        if heading:
            finish()
            current_id, current_title = heading.groups()
            continue
        if current_id is None:
            continue
        field_match = FIELD.match(raw_line)
        if field_match:
            key, value = field_match.groups()
            current_fields[key] = value.strip()
        elif raw_line and not raw_line.startswith("#") and current_fields:
            # Catalog fields are presently single bullets, but accepting an
            # indented continuation keeps the parser compatible with wrapping.
            if raw_line.startswith("  "):
                last_key = next(reversed(current_fields))
                current_fields[last_key] += " " + raw_line.strip()
    finish()

    ids = [control.control_id for control in parsed]
    if len(ids) != len(set(ids)):
        raise ValueError("Catalog contains duplicate control IDs")
    if len(parsed) != 35:
        raise ValueError(f"Expected 35 controls in standard 0.1, found {len(parsed)}")
    gates = [control.gate for control in parsed if control.gate]
    expected_gates = {"G-01", "G-02", "G-03", "G-04"}
    if set(gates) != expected_gates or len(gates) != len(expected_gates):
        raise ValueError("Catalog must map each foundational gate G-01 through G-04 exactly once")
    return Catalog(
        standard_version=version_match.group(1),
        path=str(catalog_path),
        controls=tuple(parsed),
    )
