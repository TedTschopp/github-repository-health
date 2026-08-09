"""Render repository-health assessment and leadership reports.

The renderer consumes the version 1.0 assessment payload emitted by the
repository-health evaluator.  It intentionally does not collect evidence or
recalculate the assessment.  Its job is to preserve the evaluator's result,
make evidence limitations visible, and translate assessed gaps into a short,
ordered leadership action plan.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA_VERSION = "1.0"
LEADERSHIP_SCHEMA = "repository-health-leadership-summary/v1"
PROVISIONAL_STANDARD_VERSION = "0.1.0-draft"
ACTION_MAP_PATH = Path(__file__).with_name("control_actions.json")

DIMENSION_NAMES = {
    "SPI": "Source-to-production integrity",
    "BTC": "Build, test, and validation health",
    "CGD": "Change governance and branch discipline",
    "SSC": "Security and software supply-chain health",
    "OWM": "Ownership and maintainability",
    "DCR": "Documentation and contributor readiness",
    "RRO": "Release, recovery, and operational readiness",
    "RLP": "Repository lifecycle and portfolio hygiene",
}

LEADERSHIP_DIMENSION_NAMES = {
    "SPI": "the connection between approved source and live outputs",
    "BTC": "build and validation reliability",
    "CGD": "change control and working discipline",
    "SSC": "security and outside-component health",
    "OWM": "ownership and maintainability",
    "DCR": "documentation and contributor readiness",
    "RRO": "release, recovery, and operational readiness",
    "RLP": "repository lifecycle and portfolio hygiene",
}

GATE_NAMES = {
    "G-01": "Main is ready to build, validate, and release",
    "G-02": "Every current output is traceable to Main",
    "G-03": "Every change to Main is controlled and recorded",
    "G-04": "Main and production-critical references are protected",
}

DORA_NAMES = {
    "change_lead_time": "Time from an accepted change to use",
    "lead_time_for_changes": "Time from an accepted change to use",
    "deployment_frequency": "How often changes reach users",
    "failed_deployment_recovery_time": "Time to recover from an unsuccessful release",
    "mean_time_to_restore": "Time to recover from an unsuccessful release",
    "change_fail_rate": "Share of releases that require correction",
    "deployment_rework_rate": "Share of release work spent correcting prior releases",
}

CONFORMANCE_LABELS = {
    "met": "Met",
    "partially_met": "Partially met",
    "unmet": "Unmet",
    "unknown": "Unknown",
    "not_applicable": "N/A",
}

GAP_STATES = {"partially_met", "unmet", "unknown"}


class ReportInputError(ValueError):
    """Raised when a report cannot be rendered from the supplied assessment."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def _first(data: Mapping[str, Any], *paths: str, default: Any = None) -> Any:
    """Return the first non-empty value at one of the dotted paths."""

    for path in paths:
        current: Any = data
        found = True
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                found = False
                break
            current = current[part]
        if found and current is not None and current != "":
            return current
    return default


def _text(value: Any, default: str = "Not supplied") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isfinite(value):
            return f"{value:.1f}" if not value.is_integer() else str(int(value))
        return str(value)
    if isinstance(value, Mapping):
        return "; ".join(f"{_humanize(str(k))}: {_text(v)}" for k, v in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = [_text(item, default="") for item in value]
        return "; ".join(item for item in values if item) or default
    return str(value).strip() or default


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _format_score(value: Any) -> str:
    number = _number(value)
    return "Not supplied" if number is None else f"{number:.1f}"


def _humanize(value: str) -> str:
    text = re.sub(r"[_-]+", " ", value).strip()
    return text[:1].upper() + text[1:] if text else "Not supplied"


def _md(value: Any) -> str:
    """Encode untrusted data for a single Markdown line or table cell."""

    text = re.sub(r"\s*[\r\n]+\s*", " ", _text(value)).strip()
    text = html.escape(text, quote=True)
    text = text.replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "(", ")", "!", "|"):
        text = text.replace(character, f"\\{character}")
    return text


def _inline(value: Any, default: str = "Not supplied") -> str:
    """Alias that documents safe use outside a Markdown table."""

    return _md(_text(value, default=default))


def _plain_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in _sequence(value):
        if isinstance(item, Mapping):
            rendered = _first(
                item,
                "message",
                "description",
                "reason",
                "limitation",
                "gap",
                default=None,
            )
            if rendered is None:
                rendered = _text(item)
        else:
            rendered = _text(item, default="")
        if rendered and rendered not in result:
            result.append(rendered)
    return result


def _normalize_conformance(value: Any, applicable: Any = True) -> str:
    if applicable is False:
        return "not_applicable"
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "unknown").lower()).strip("_")
    aliases = {
        "met": "met",
        "pass": "met",
        "passed": "met",
        "partially_met": "partially_met",
        "partial": "partially_met",
        "partially": "partially_met",
        "concern": "partially_met",
        "unmet": "unmet",
        "fail": "unmet",
        "failed": "unmet",
        "unknown": "unknown",
        "e0": "unknown",
        "n_a": "not_applicable",
        "na": "not_applicable",
        "not_applicable": "not_applicable",
    }
    return aliases.get(normalized, "unknown")


def load_action_map(path: str | Path = ACTION_MAP_PATH) -> dict[str, dict[str, Any]]:
    """Load and validate the controlled plain-language action map."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportInputError(f"Unable to load control action map {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReportInputError("Control action map must be a JSON object keyed by control ID")

    required = {
        "title",
        "action",
        "owner_role",
        "why_it_matters",
        "expected_evidence_or_outcome",
        "priority_order",
    }
    expected_ids = {
        *(f"SPI-{number:02d}" for number in range(1, 5)),
        *(f"BTC-{number:02d}" for number in range(1, 6)),
        *(f"CGD-{number:02d}" for number in range(1, 7)),
        *(f"SSC-{number:02d}" for number in range(1, 5)),
        *(f"OWM-{number:02d}" for number in range(1, 5)),
        *(f"DCR-{number:02d}" for number in range(1, 5)),
        *(f"RRO-{number:02d}" for number in range(1, 5)),
        *(f"RLP-{number:02d}" for number in range(1, 5)),
    }
    missing_ids = expected_ids - set(payload)
    extra_ids = set(payload) - expected_ids
    if missing_ids or extra_ids:
        raise ReportInputError(
            "Control action map must cover exactly the 35 controls; "
            f"missing={sorted(missing_ids)}, extra={sorted(extra_ids)}"
        )
    for control_id, item in payload.items():
        if not isinstance(item, dict):
            raise ReportInputError(f"Action mapping for {control_id} must be an object")
        missing_fields = required - set(item)
        if missing_fields:
            raise ReportInputError(
                f"Action mapping for {control_id} is missing {sorted(missing_fields)}"
            )
    return payload


def load_assessment(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportInputError(f"Unable to load assessment {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReportInputError("Assessment JSON must be an object")
    return payload


def _normalize_controls(
    assessment: Mapping[str, Any], action_map: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    controls_payload = _first(assessment, "controls", "control_results", default=[])
    if isinstance(controls_payload, Mapping):
        source_controls = []
        for control_id, result in controls_payload.items():
            item = dict(_mapping(result))
            item.setdefault("control_id", control_id)
            source_controls.append(item)
    else:
        source_controls = [dict(_mapping(item)) for item in _sequence(controls_payload)]

    findings_by_control: dict[str, list[dict[str, Any]]] = {}
    for raw_finding in _sequence(_first(assessment, "findings", default=[])):
        finding = dict(_mapping(raw_finding))
        control_id = _text(
            _first(finding, "control_id", "control", default=""), default=""
        ).upper()
        if control_id:
            findings_by_control.setdefault(control_id, []).append(finding)

    result: list[dict[str, Any]] = []
    for index, raw in enumerate(source_controls):
        control_id = _text(
            _first(raw, "control_id", "id", default=""), default=""
        ).upper()
        if not control_id:
            continue
        mapping = _mapping(action_map.get(control_id))
        applicable_value = _first(raw, "applicable", default=True)
        conformance = _normalize_conformance(
            _first(raw, "conformance", "rating", "status", default="Unknown"),
            applicable=applicable_value,
        )
        applicable = conformance != "not_applicable" and applicable_value is not False
        gate = _text(_first(raw, "gate", "foundational_gate", default=""), default="")
        if gate.lower() in {"none", "n/a", "na"}:
            gate = ""
        dimension = _text(
            _first(raw, "dimension", default=control_id.split("-", 1)[0]),
            default=control_id.split("-", 1)[0],
        ).upper()
        evidence_ids = [
            _text(value, default="")
            for value in _sequence(
                _first(raw, "evidence_ids", "evidence", default=[])
            )
            if _text(value, default="")
        ]
        result.append(
            {
                "control_id": control_id,
                "title": _text(
                    _first(raw, "title", default=mapping.get("title")),
                    default=control_id,
                ),
                "dimension": dimension,
                "gate": gate,
                "applicable": applicable,
                "applicability_reason": _text(
                    _first(raw, "applicability_reason", default=""), default=""
                ),
                "conformance": conformance,
                "conformance_label": CONFORMANCE_LABELS[conformance],
                "points": _number(_first(raw, "points", default=None)),
                "assurance": _text(
                    _first(raw, "assurance", "evidence_level", default="E0"),
                    default="E0",
                ).upper(),
                "minimum_assurance": _text(
                    _first(raw, "minimum_assurance", default=""), default=""
                ).upper(),
                "evidence_ids": evidence_ids,
                "rationale": _text(
                    _first(raw, "rationale", "reason", "condition", default=""),
                    default="",
                ),
                "remediation": _text(
                    _first(raw, "remediation", default=""), default=""
                ),
                "source": _text(_first(raw, "source", default=""), default=""),
                "findings": findings_by_control.get(control_id, []),
                "input_order": index,
            }
        )
    return result


def _normalize_gates(
    assessment: Mapping[str, Any], controls: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    gate_payload = _first(assessment, "gates", "foundational_gates", default={})
    source: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(gate_payload, Mapping):
        source = [(str(gate_id).upper(), _mapping(value)) for gate_id, value in gate_payload.items()]
    else:
        for value in _sequence(gate_payload):
            item = _mapping(value)
            gate_id = _text(_first(item, "gate_id", "id", "gate", default=""), default="").upper()
            if gate_id:
                source.append((gate_id, item))

    control_by_gate = {
        _text(control.get("gate"), default="").upper(): control
        for control in controls
        if _text(control.get("gate"), default="")
    }
    source_by_id = {gate_id: item for gate_id, item in source}
    gate_ids = [gate_id for gate_id in GATE_NAMES if gate_id in source_by_id or gate_id in control_by_gate]
    result: list[dict[str, Any]] = []
    for gate_id in gate_ids:
        item = source_by_id.get(gate_id, {})
        control = control_by_gate.get(gate_id, {})
        status = _text(_first(item, "status", "outcome", default=""), default="").title()
        if not status:
            conformance = control.get("conformance")
            status = {
                "met": "Pass",
                "partially_met": "Fail",
                "unmet": "Fail",
                "unknown": "Unknown",
                "not_applicable": "N/A",
            }.get(str(conformance), "Unknown")
        if status.lower() in {"passed", "met"}:
            status = "Pass"
        elif status.lower() in {"failed", "fail", "unmet", "partially met"}:
            status = "Fail"
        elif status.lower() in {"n/a", "na", "not applicable"}:
            status = "N/A"
        elif status.lower() not in {"pass", "unknown"}:
            status = "Unknown"
        result.append(
            {
                "gate_id": gate_id,
                "name": GATE_NAMES.get(gate_id, gate_id),
                "control_id": _text(
                    _first(item, "control_id", default=control.get("control_id")),
                    default="Not supplied",
                ),
                "status": status,
                "rationale": _text(
                    _first(item, "rationale", "reason", default=control.get("rationale")),
                    default="",
                ),
            }
        )
    return result


def _repository_summary(assessment: Mapping[str, Any]) -> dict[str, Any]:
    repository = _mapping(_first(assessment, "repository", "profile.repository", default={}))
    profile = _mapping(_first(assessment, "profile", default={}))
    classification = _mapping(_first(assessment, "classification", default={}))
    if isinstance(_first(assessment, "repository", default=None), str):
        repository = {"name": _first(assessment, "repository")}

    def choose(*paths: str, default: Any = None) -> Any:
        combined = {
            "repository": repository,
            "profile": profile,
            "classification": classification,
            **assessment,
        }
        return _first(combined, *paths, default=default)

    return {
        "name": _text(
            choose(
                "repository.identity",
                "repository.full_name",
                "repository.name_with_owner",
                "repository.name",
                "profile.repository_name",
                "repository_id",
                default="Unknown repository",
            ),
            default="Unknown repository",
        ),
        "url": _text(choose("repository.url", "profile.repository_url", default=""), default=""),
        "owner": _text(
            choose(
                "classification.owner",
                "repository.owner_role",
                "repository.owner",
                "profile.repository_owner",
                default="Not supplied",
            )
        ),
        "default_branch": _text(
            choose(
                "repository.default_branch",
                "repository.main_branch",
                "profile.main_branch",
                default="Not supplied",
            )
        ),
        "assessed_revision": _text(
            choose(
                "repository.assessed_revision",
                "repository.main_sha",
                "repository.head",
                "repository.head_sha",
                "repository.assessed_checkout_sha",
                "facts.head_sha",
                default="Not supplied",
            )
        ),
        "type": _text(
            choose(
                "classification.type",
                "classification.repository_type",
                "repository.type",
                "profile.repository_type",
                default="Unknown",
            )
        ),
        "lifecycle": _text(
            choose(
                "classification.lifecycle",
                "classification.lifecycle_state",
                "repository.lifecycle",
                "profile.lifecycle",
                default="Unknown",
            )
        ),
        "risk_tier": _text(
            choose(
                "classification.risk_tier",
                "repository.risk_tier",
                "profile.risk_tier",
                default="Unknown",
            )
        ),
    }


def _methodology_summary(assessment: Mapping[str, Any]) -> dict[str, Any]:
    classification = _mapping(_first(assessment, "classification", default={}))
    methodology = _mapping(
        _first(assessment, "methodology", "classification.methodology", default={})
    )
    combined = {"classification": classification, "methodology": methodology}
    return {
        "declared": _text(
            _first(
                combined,
                "methodology.declared",
                "classification.declared_methodology",
                default="Not supplied",
            )
        ),
        "observed": _text(
            _first(
                combined,
                "methodology.observed",
                "classification.observed_methodology",
                "classification.methodology",
                default="Unknown",
            )
        ),
        "confidence": _text(
            _first(
                combined,
                "methodology.confidence",
                "classification.methodology_confidence",
                default="Unknown",
            )
        ),
        "contradictions": _plain_list(
            _first(
                combined,
                "methodology.contradictions",
                "classification.contradictions",
                "classification.methodology_contradictions",
                default=[],
            )
        ),
    }


def _score_summary(assessment: Mapping[str, Any]) -> dict[str, Any]:
    score = _mapping(_first(assessment, "score", default={}))
    assurance = _mapping(_first(assessment, "assurance", default={}))
    gate_cap = _mapping(_first(assessment, "gate_cap", default={}))
    cap_applied = _first(
        score,
        "cap_active",
        "cap_applied",
        default=_first(gate_cap, "active", "applied", default=False),
    )
    return {
        "raw": _number(_first(score, "raw", "raw_score", default=_first(assessment, "raw_score"))),
        "effective": _number(
            _first(
                score,
                "effective",
                "final_score",
                default=_first(assessment, "final_score", "effective_score"),
            )
        ),
        "calculated_grade": _text(
            _first(score, "calculated_grade", default="Not supplied")
        ),
        "effective_grade": _text(
            _first(score, "effective_grade", "grade", default=_first(assessment, "grade"))
        ),
        "calculated_maturity": _text(
            _first(score, "calculated_maturity", default="Not supplied")
        ),
        "effective_maturity": _text(
            _first(score, "effective_maturity", "maturity", default=_first(assessment, "maturity"))
        ),
        "cap_applied": bool(cap_applied),
        "cap_reason": _text(
            _first(score, "cap_reason", default=_first(gate_cap, "reason", default="")),
            default="",
        ),
        "assurance_index": _number(
            _first(assurance, "index", "score", default=_first(assessment, "assurance_index"))
        ),
        "assurance_label": _text(
            _first(assurance, "label", default=_first(assessment, "assurance_label"))
        ),
        "assurance_distribution": _mapping(
            _first(assurance, "distribution", default={})
        ),
    }


def _normalize_dimensions(assessment: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = _first(assessment, "dimensions", "dimension_results", default={})
    source: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(payload, Mapping):
        source = [(str(code).upper(), _mapping(item)) for code, item in payload.items()]
    else:
        for item in _sequence(payload):
            data = _mapping(item)
            code = _text(_first(data, "code", "id", "dimension", default=""), default="").upper()
            if code:
                source.append((code, data))
    by_code = {code: item for code, item in source}
    ordered = [code for code in DIMENSION_NAMES if code in by_code]
    ordered.extend(code for code in by_code if code not in ordered)
    return [
        {
            "code": code,
            "name": _text(_first(by_code[code], "name", default=DIMENSION_NAMES.get(code, code))),
            "score": _number(_first(by_code[code], "score", "value", default=None)),
            "applicable_controls": _first(
                by_code[code], "applicable_controls", "control_count", default=None
            ),
            "applicability_coverage": _first(
                by_code[code], "applicability_coverage", default=None
            ),
            "evidence_coverage": _first(
                by_code[code], "evidence_coverage", "coverage", default=None
            ),
        }
        for code in ordered
    ]


def _assessment_basis(control: Mapping[str, Any]) -> str:
    state = str(control.get("conformance"))
    if state == "unknown":
        return "The assessment did not have enough current evidence to confirm that this requirement is met."
    if state == "unmet":
        return "The assessment found that this requirement does not yet meet the standard."
    if state == "partially_met":
        return "The assessment found that this requirement is only partly in place or partly evidenced."
    return f"The assessment rated this requirement as {CONFORMANCE_LABELS.get(state, 'not met')}."


def _finding_priority(control: Mapping[str, Any]) -> int:
    values: list[int] = []
    for finding in _sequence(control.get("findings")):
        raw = _text(_first(_mapping(finding), "priority", "severity", default=""), default="").upper()
        match = re.search(r"P([0-3])", raw)
        if match:
            values.append(int(match.group(1)))
        elif raw in {"CRITICAL", "URGENT"}:
            values.append(0)
        elif raw == "HIGH":
            values.append(1)
        elif raw in {"MODERATE", "MEDIUM"}:
            values.append(2)
        elif raw == "LOW":
            values.append(3)
    return min(values, default=4)


def _priority_tuple(
    control: Mapping[str, Any], mapping: Mapping[str, Any]
) -> tuple[Any, ...]:
    gate_priority = 0 if control.get("gate_is_gap") else 1
    severity = {"unmet": 0, "unknown": 1, "partially_met": 2}.get(
        str(control.get("conformance")), 3
    )
    return (
        gate_priority,
        _finding_priority(control),
        severity,
        int(mapping.get("priority_order", 999)),
        _text(control.get("control_id")),
    )


def _priority_basis(control: Mapping[str, Any]) -> str:
    gate = _text(control.get("gate"), default="")
    if gate and control.get("gate_is_gap"):
        return f"First because {gate} is a foundational requirement and a failed or unknown result limits the standing."
    finding_priority = _finding_priority(control)
    if finding_priority < 4:
        label = {0: "Critical", 1: "High", 2: "Moderate", 3: "Lower"}[finding_priority]
        return f"The assessment marks this as {label} priority; ties are ordered by how completely the requirement is unmet."
    state = str(control.get("conformance"))
    if state == "unmet":
        return "Ordered ahead of partial gaps because the assessment found the requirement unmet."
    if state == "unknown":
        return "Ordered to close an evidence gap that currently counts as zero and lowers confidence in the result."
    return "Ordered after failed and unknown requirements because the control is already partly in place."


def _standing_impact(
    control: Mapping[str, Any], gates: Sequence[Mapping[str, Any]], score: Mapping[str, Any]
) -> str:
    gate = _text(control.get("gate"), default="")
    active_gate_gaps = [
        item for item in gates if str(item.get("status")) in {"Fail", "Unknown"}
    ]
    gate_status = next(
        (
            str(item.get("status"))
            for item in gates
            if str(item.get("gate_id")) == gate
        ),
        "",
    )
    if gate and gate_status in {"Fail", "Unknown"}:
        if score.get("cap_applied") or active_gate_gaps:
            if len(active_gate_gaps) > 1:
                return (
                    f"Closes one of {len(active_gate_gaps)} foundational gaps that keep the standing "
                    "at D / Developing or lower. The cap remains until every failed or unknown "
                    "foundational requirement is resolved with sufficient evidence."
                )
            return (
                f"Removes {gate} as the identified reason for the D / Developing cap once the "
                "required outcome and evidence are confirmed; the underlying score can then determine standing."
            )
        return (
            f"Protects the {gate} foundational result. If it is currently failed or unknown, resolving it "
            "removes that reason for a D / Developing cap."
        )

    dimension = LEADERSHIP_DIMENSION_NAMES.get(
        _text(control.get("dimension"), default="").upper(),
        "repository health",
    )
    state = str(control.get("conformance"))
    if state == "unknown":
        return (
            f"Replaces an Unknown in {dimension} with a supported result and improves assurance. "
            "The score rises only if the evidence shows that the requirement is met or partially met."
        )
    if state == "partially_met":
        return (
            f"Can move one control in {dimension} from half credit to full credit. The exact grade "
            "change depends on the other applicable controls and any active foundational cap."
        )
    return (
        f"Can move one control in {dimension} from zero toward full credit. The exact grade change "
        "depends on the other applicable controls and any active foundational cap."
    )


def _build_actions(
    controls: Sequence[Mapping[str, Any]],
    action_map: Mapping[str, Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    score: Mapping[str, Any],
    limit: int = 7,
) -> list[dict[str, Any]]:
    candidates: list[tuple[tuple[Any, ...], Mapping[str, Any], Mapping[str, Any]]] = []
    gate_statuses = {
        str(gate.get("gate_id")): str(gate.get("status")) for gate in gates
    }
    for control in controls:
        if not control.get("applicable") or control.get("conformance") not in GAP_STATES:
            continue
        control_id = _text(control.get("control_id"), default="").upper()
        mapping = action_map.get(control_id)
        if not mapping:
            # The versioned action map is deliberately closed over all 0.1.0-draft
            # controls. Future controls are not converted into invented work.
            continue
        ranked_control = dict(control)
        ranked_control["gate_is_gap"] = bool(
            control.get("gate")
            and gate_statuses.get(str(control.get("gate"))) in {"Fail", "Unknown"}
        )
        candidates.append(
            (_priority_tuple(ranked_control, mapping), ranked_control, mapping)
        )

    candidates.sort(key=lambda item: item[0])
    actions: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    for _, control, mapping in candidates:
        distinct_key = re.sub(r"\W+", " ", str(mapping["action"]).lower()).strip()
        if distinct_key in seen_actions:
            continue
        seen_actions.add(distinct_key)
        action_text = _text(mapping["action"])
        if control.get("conformance") == "unknown":
            action_text = (
                "Confirm with current evidence whether this requirement is in place. "
                f"If it is not, complete this improvement: {action_text}"
            )
        actions.append(
            {
                "rank": len(actions) + 1,
                "action_id": f"ACT-{_text(control['control_id']).replace('-', '')}",
                "control_ids": [_text(control["control_id"])],
                "gate_ids": [_text(control["gate"])] if control.get("gate") else [],
                "title": _text(mapping["title"]),
                "action": action_text,
                "owner_role": _text(mapping["owner_role"]),
                "why_it_matters": _text(mapping["why_it_matters"]),
                "expected_evidence_or_outcome": _text(
                    mapping["expected_evidence_or_outcome"]
                ),
                "standing_impact": _standing_impact(control, gates, score),
                "assessment_basis": _assessment_basis(control),
                "priority_basis": _priority_basis(control),
                "current_rating": _text(control["conformance_label"]),
                "current_assurance": _text(control["assurance"]),
            }
        )
        if len(actions) >= limit:
            break
    return actions


def _dora_summary(assessment: Mapping[str, Any]) -> dict[str, Any]:
    dora = _mapping(_first(assessment, "dora", "dora_outcomes", default={}))
    metrics = _mapping(_first(dora, "metrics", default={}))
    period_start = _first(dora, "period_start", default=None)
    period_end = _first(dora, "period_end", default=None)
    overall_window = (
        f"{_text(period_start)} to {_text(period_end)}"
        if period_start is not None or period_end is not None
        else None
    )
    rendered_metrics: list[dict[str, Any]] = []
    for metric_id, raw in metrics.items():
        item = _mapping(raw)
        value = _first(item, "value", "result", default=raw if not item else None)
        rendered_metrics.append(
            {
                "metric_id": str(metric_id),
                "name": DORA_NAMES.get(str(metric_id), _humanize(str(metric_id))),
                "value": value,
                "window": _first(
                    item, "window", "observation_window", default=overall_window
                ),
                "limitation": _first(item, "limitation", "note", default=None),
            }
        )
    available = bool(_first(dora, "available", default=bool(rendered_metrics)))
    return {
        "informative_only": True,
        "available": available,
        "reason": _text(
            _first(dora, "reason", default=""), default=""
        ),
        "metrics": rendered_metrics,
        "service": _first(dora, "service", "scope", default=None),
        "period_start": period_start,
        "period_end": period_end,
        "context": _first(dora, "context", default=None),
        "limitations": _plain_list(
            _first(dora, "limitations", "limitation", default=[])
        ),
    }


def _limitations(
    assessment: Mapping[str, Any], controls: Sequence[Mapping[str, Any]], action_map: Mapping[str, Any]
) -> list[str]:
    limitations = _plain_list(
        _first(assessment, "limitations", "evidence_limitations", default=[])
    )
    limitations.extend(
        item
        for item in _plain_list(_first(assessment, "evidence_gaps", default=[]))
        if item not in limitations
    )
    unknown_count = sum(
        1
        for control in controls
        if control.get("applicable") and control.get("conformance") == "unknown"
    )
    if unknown_count:
        statement = (
            f"{unknown_count} applicable control{'s' if unknown_count != 1 else ''} "
            "remain Unknown. Unknown evidence cannot count as passing and lowers assurance."
        )
        if statement not in limitations:
            limitations.append(statement)
    expected_ids = set(action_map)
    present_ids = {str(control.get("control_id")) for control in controls}
    missing_ids = expected_ids - present_ids
    if missing_ids:
        limitations.append(
            f"The assessment payload supplied {len(present_ids & expected_ids)} of 35 standard control "
            f"results. Missing controls ({', '.join(sorted(missing_ids))}) were not converted into actions."
        )
    return limitations


def build_leadership_summary(
    assessment: Mapping[str, Any], *, action_map_path: str | Path = ACTION_MAP_PATH
) -> dict[str, Any]:
    """Build the compact, structured leadership report.

    Only applicable controls assessed as Partially met, Unmet, or Unknown can
    become actions. This prevents missing or passing controls from being
    translated into invented work.
    """

    if not isinstance(assessment, Mapping):
        raise ReportInputError("Assessment must be a mapping")
    action_map = load_action_map(action_map_path)
    controls = _normalize_controls(assessment, action_map)
    gates = _normalize_gates(assessment, controls)
    score = _score_summary(assessment)
    repository = _repository_summary(assessment)
    limitations = _limitations(assessment, controls, action_map)
    dora = _dora_summary(assessment)
    actions = _build_actions(controls, action_map, gates, score, limit=7)

    standard_version = _text(
        _first(assessment, "standard_version", default=PROVISIONAL_STANDARD_VERSION),
        default=PROVISIONAL_STANDARD_VERSION,
    )
    disclosure = (
        f"This assessment uses the provisional Repository Health Standard {standard_version}. "
        "Its thresholds and scoring remain subject to calibration through the planned field pilot."
    )
    dora_disclosure = (
        "Delivery outcome measures are shown for context only and do not change the repository-health score, grade, maturity, or foundational results."
    )
    generated_at = _text(
        _first(assessment, "generated_at", default=datetime.now(timezone.utc).isoformat())
    )
    active_gate_gaps = [
        gate["gate_id"] for gate in gates if gate["status"] in {"Fail", "Unknown"}
    ]
    return {
        "schema_version": LEADERSHIP_SCHEMA,
        "assessment_schema_version": _text(
            _first(assessment, "schema_version", default="Unknown")
        ),
        "standard_version": standard_version,
        "assessment_id": _text(
            _first(assessment, "assessment_id", default="Not supplied")
        ),
        "generated_at": generated_at,
        "repository": repository,
        "standing": {
            "raw_score": score["raw"],
            "effective_score": score["effective"],
            "grade": score["effective_grade"],
            "maturity": score["effective_maturity"],
            "assurance_index": score["assurance_index"],
            "assurance_label": score["assurance_label"],
            "gate_cap": {
                "applied": bool(score["cap_applied"] or active_gate_gaps),
                "triggering_gates": active_gate_gaps,
                "reason": score["cap_reason"],
            },
        },
        "evidence": {
            "supplied_standard_control_count": len(
                {
                    str(control.get("control_id"))
                    for control in controls
                    if str(control.get("control_id")) in action_map
                }
            ),
            "missing_standard_control_count": len(
                set(action_map)
                - {
                    str(control.get("control_id"))
                    for control in controls
                }
            ),
            "unknown_control_count": sum(
                1
                for control in controls
                if control.get("applicable") and control.get("conformance") == "unknown"
            ),
            "limitations": limitations,
        },
        "top_actions": actions,
        "dora": dora,
        "disclosures": [disclosure, dora_disclosure],
    }


def _standing_sentence(summary: Mapping[str, Any]) -> str:
    standing = _mapping(summary.get("standing"))
    repository = _mapping(summary.get("repository"))
    score = _format_score(standing.get("effective_score"))
    grade = _inline(standing.get("grade"))
    maturity = _inline(standing.get("maturity"))
    assurance = _inline(standing.get("assurance_label"))
    sentence = (
        f"{_inline(repository.get('name'))} currently stands at **{score} / {grade} / {maturity}** "
        f"with **{assurance}** evidence assurance."
    )
    gate_cap = _mapping(standing.get("gate_cap"))
    if gate_cap.get("applied"):
        gates = _sequence(gate_cap.get("triggering_gates"))
        detail = f" ({', '.join(_inline(item) for item in gates)})" if gates else ""
        sentence += (
            f" A foundational cap is active{detail}, so the standing cannot rise above D / Developing "
            "until every failed or unknown foundational result is resolved."
        )
    return sentence


def render_leadership_summary(
    assessment: Mapping[str, Any], *, action_map_path: str | Path = ACTION_MAP_PATH
) -> str:
    """Render an action-oriented leadership summary in plain-language Markdown."""

    summary = build_leadership_summary(assessment, action_map_path=action_map_path)
    repository = _mapping(summary["repository"])
    standing = _mapping(summary["standing"])
    evidence = _mapping(summary["evidence"])
    actions = _sequence(summary["top_actions"])
    lines = [
        "# Repository Health Leadership Summary",
        "",
        f"**Repository:** {_inline(repository.get('name'))}",
        f"**Assessment:** {_inline(summary.get('assessment_id'))}",
        f"**Generated:** {_inline(summary.get('generated_at'))}",
        "",
        "> **How to read this:** Main means the repository's approved source line for accepted work. "
        "The standing combines health requirements, while evidence assurance says how much current proof supports the result.",
        "",
        "## Current standing",
        "",
        _standing_sentence(summary),
        "",
        "| Leadership view | Result |",
        "| --- | --- |",
        f"| Effective score | {_format_score(standing.get('effective_score'))} out of 100 |",
        f"| Grade and maturity | {_md(standing.get('grade'))} / {_md(standing.get('maturity'))} |",
        f"| Evidence assurance | {_md(standing.get('assurance_label'))} ({_format_score(standing.get('assurance_index'))}) |",
        f"| Risk tier | {_md(repository.get('risk_tier'))} |",
        f"| Accountable repository owner | {_md(repository.get('owner'))} |",
        "",
    ]

    action_count = len(actions)
    lines.extend(
        [
            f"## Next {action_count} action{'s' if action_count != 1 else ''}, in order",
            "",
        ]
    )
    if not actions:
        missing_count = int(evidence.get("missing_standard_control_count") or 0)
        if missing_count:
            lines.extend(
                [
                    f"No ordered action plan can be produced from the supplied results because {missing_count} standard control result{'s are' if missing_count != 1 else ' is'} missing. Obtain a complete assessment before deciding that no corrective work is needed.",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "No corrective action was generated because every applicable control supplied in the assessment was Met or N/A. Continue routine monitoring and close the evidence limitations below.",
                    "",
                ]
            )
    else:
        for action in actions:
            item = _mapping(action)
            control_reference = ", ".join(
                _inline(value) for value in _sequence(item.get("control_ids"))
            )
            lines.extend(
                [
                    f"### {_inline(item['rank'])}. {_inline(item.get('title'))}",
                    "",
                    f"- **Do next:** {_inline(item.get('action'))}",
                    f"- **Accountable role:** {_inline(item.get('owner_role'))}",
                    f"- **Why it matters:** {_inline(item.get('why_it_matters'))}",
                    f"- **Evidence of completion:** {_inline(item.get('expected_evidence_or_outcome'))}",
                    f"- **Standing impact:** {_inline(item.get('standing_impact'))}",
                    f"- **Why it is ordered here:** {_inline(item.get('priority_basis'))}",
                    f"- **Assessment basis:** {_inline(item.get('assessment_basis'))}",
                    f"- **Standard reference:** {control_reference} (current result: {_inline(item.get('current_rating'))}; evidence: {_inline(item.get('current_assurance'))})",
                    "",
                ]
            )

    limitations = _sequence(evidence.get("limitations"))
    lines.extend(["## Evidence limitations", ""])
    if limitations:
        lines.extend(f"- {_inline(item)}" for item in limitations)
    else:
        lines.append("- No additional limitation was supplied by the assessment.")
    lines.append("")

    dora = _mapping(summary.get("dora"))
    lines.extend(
        [
            "## Delivery outcomes — context only",
            "",
            "These measures describe delivery performance. They are **informative only** and are not included in the health score, grade, maturity, or foundational results.",
            "",
        ]
    )
    if dora.get("available") and dora.get("metrics"):
        lines.extend(["| Outcome | Value |", "| --- | --- |"])
        for metric in _sequence(dora.get("metrics")):
            item = _mapping(metric)
            lines.append(f"| {_md(item.get('name'))} | {_md(item.get('value'))} |")
        lines.append("")
        if dora.get("context"):
            lines.extend([f"**Context:** {_inline(dora.get('context'))}", ""])
        if dora.get("limitations"):
            lines.append("**Delivery-data limitations:**")
            lines.extend(
                f"- {_inline(item)}" for item in _sequence(dora.get("limitations"))
            )
            lines.append("")
    else:
        reason = _inline(dora.get("reason"), default="No delivery outcome data was supplied.")
        lines.extend([reason, ""])

    lines.extend(
        [
            "## Important disclosures",
            "",
            *[f"- {_inline(item)}" for item in _sequence(summary.get("disclosures"))],
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_health_assessment(
    assessment: Mapping[str, Any], *, action_map_path: str | Path = ACTION_MAP_PATH
) -> str:
    """Render the full evidence-facing assessment report in Markdown."""

    action_map = load_action_map(action_map_path)
    controls = _normalize_controls(assessment, action_map)
    gates = _normalize_gates(assessment, controls)
    dimensions = _normalize_dimensions(assessment)
    repository = _repository_summary(assessment)
    methodology = _methodology_summary(assessment)
    score = _score_summary(assessment)
    limitations = _limitations(assessment, controls, action_map)
    leadership = build_leadership_summary(assessment, action_map_path=action_map_path)
    dora = _mapping(leadership["dora"])
    standard_version = _text(
        _first(assessment, "standard_version", default=PROVISIONAL_STANDARD_VERSION)
    )
    lines = [
        "# Repository Health Assessment",
        "",
        f"> **Provisional assessment:** This report uses Repository Health Standard {_inline(standard_version)}. "
        "Thresholds and scoring remain subject to calibration through the planned field pilot.",
        "",
        "## Assessment identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Assessment ID | {_md(_first(assessment, 'assessment_id', default='Not supplied'))} |",
        f"| Assessment schema | {_md(_first(assessment, 'schema_version', default='Not supplied'))} |",
        f"| Standard version | {_md(standard_version)} |",
        f"| Standard status | {_md(_first(assessment, 'standard_status', default='Provisional'))} |",
        f"| Generated | {_md(_first(assessment, 'generated_at', default='Not supplied'))} |",
        f"| Assessor | {_md(_first(assessment, 'assessment.assessor', default='Not supplied'))} |",
        f"| Reviewer | {_md(_first(assessment, 'assessment.reviewer', default='Not supplied'))} |",
        f"| Evidence cutoff | {_md(_first(assessment, 'assessment.evidence_cutoff', default='Not supplied'))} |",
        f"| Next review | {_md(_first(assessment, 'assessment.next_review', default='Not supplied'))} |",
        f"| Repository | {_md(repository['name'])} |",
        f"| Repository URL | {_md(repository['url'])} |",
        f"| Repository owner | {_md(repository['owner'])} |",
        f"| Main/default branch | {_md(repository['default_branch'])} |",
        f"| Assessed revision | {_md(repository['assessed_revision'])} |",
        f"| Deployable or publishable units | {_md(_first(assessment, 'repository.deployable_units', default='None supplied'))} |",
        f"| Production correspondence | {_md(_first(assessment, 'repository.production_correspondence', default='Not supplied'))} |",
        f"| Repository type | {_md(repository['type'])} |",
        f"| Lifecycle | {_md(repository['lifecycle'])} |",
        f"| Risk tier | {_md(repository['risk_tier'])} |",
        "",
        "## Methodology classification",
        "",
        "| View | Result |",
        "| --- | --- |",
        f"| Declared method | {_md(methodology['declared'])} |",
        f"| Observed method | {_md(methodology['observed'])} |",
        f"| Classification confidence | {_md(methodology['confidence'])} |",
        f"| Contradictions | {_md(methodology['contradictions'] or 'None supplied')} |",
        "",
        "### Observed workflow axes",
        "",
        "| Axis | Observation |",
        "| --- | --- |",
    ]
    methodology_axes = _mapping(
        _first(assessment, "classification.axes", "methodology.axes", default={})
    )
    if methodology_axes:
        for axis, value in methodology_axes.items():
            lines.append(f"| {_md(_humanize(str(axis)))} | {_md(value)} |")
    else:
        lines.append("| Not supplied | Classification evidence gap |")
    lines.extend(
        [
        "",
        "## Score and assurance",
        "",
        "| Result | Value |",
        "| --- | --- |",
        f"| Raw score | {_format_score(score['raw'])} |",
        f"| Calculated result | {_md(score['calculated_grade'])} / {_md(score['calculated_maturity'])} |",
        f"| Effective score | **{_format_score(score['effective'])}** |",
        f"| Effective result | **{_md(score['effective_grade'])} / {_md(score['effective_maturity'])}** |",
        f"| Foundational cap applied | {'Yes' if score['cap_applied'] else 'No'} |",
        f"| Cap reason | {_md(score['cap_reason'] or 'None supplied')} |",
        f"| Assurance | {_format_score(score['assurance_index'])} / {_md(score['assurance_label'])} |",
        "",
        "A failed or Unknown applicable foundational result limits the effective result to D / Developing, regardless of the raw score.",
        "",
        "## Foundational results",
        "",
        "| Gate | Required outcome | Control | Result | Basis |",
        "| --- | --- | --- | --- | --- |",
        ]
    )
    if gates:
        for gate in gates:
            lines.append(
                f"| {_md(gate['gate_id'])} | {_md(gate['name'])} | {_md(gate['control_id'])} | "
                f"{_md(gate['status'])} | {_md(gate['rationale'] or 'See control result')} |"
            )
    else:
        lines.append("| Not supplied | The assessment supplied no foundational result objects. | — | Unknown | Evidence gap |")
    lines.extend(["", "## Dimension results", "", "| Dimension | Score | Applicable controls | Applicability coverage | Evidence coverage |", "| --- | ---: | ---: | --- | --- |"])
    if dimensions:
        for item in dimensions:
            lines.append(
                f"| {_md(item['code'])} — {_md(item['name'])} | {_format_score(item['score'])} | "
                f"{_md(item['applicable_controls'])} | {_md(item['applicability_coverage'])} | "
                f"{_md(item['evidence_coverage'])} |"
            )
    else:
        lines.append("| Not supplied | — | — | — | — |")

    distribution = _mapping(score.get("assurance_distribution"))
    lines.extend(
        [
            "",
            "### Assurance distribution",
            "",
            "| E0 Unknown | E1 Declared | E2 Configured | E3 Demonstrated | E4 Sustained effectiveness |",
            "| ---: | ---: | ---: | ---: | ---: |",
            "| "
            + " | ".join(_md(distribution.get(level, 0)) for level in ("E0", "E1", "E2", "E3", "E4"))
            + " |",
        ]
    )

    lines.extend(
        [
            "",
            "## Control results",
            "",
            "| Control | Dimension | Gate | Applicable | Rating | Points | Evidence | Minimum | Evidence IDs | Basis |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    if controls:
        order = {control_id: index for index, control_id in enumerate(action_map)}
        for control in sorted(
            controls,
            key=lambda item: (order.get(str(item["control_id"]), 999), item["input_order"]),
        ):
            points = "—" if control["points"] is None else _format_score(control["points"])
            lines.append(
                f"| {_md(control['control_id'])} — {_md(control['title'])} | {_md(control['dimension'])} | "
                f"{_md(control['gate'] or '—')} | {'Yes' if control['applicable'] else 'No'} | "
                f"{_md(control['conformance_label'])} | {points} | {_md(control['assurance'])} | "
                f"{_md(control['minimum_assurance'] or 'Not supplied')} | "
                f"{_md(control['evidence_ids'] or 'None supplied')} | {_md(control['rationale'] or 'None supplied')} |"
            )
    else:
        lines.append("| Not supplied | — | — | — | Unknown | — | E0 | — | — | Assessment payload contained no controls |")

    evidence_records = [
        _mapping(item)
        for item in _sequence(_first(assessment, "evidence", default=[]))
    ]
    lines.extend(
        [
            "",
            "## Evidence inventory",
            "",
            "| Evidence | Source | System | Observed | Assurance | Coverage | Limitation or note |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if evidence_records:
        for evidence in evidence_records:
            lines.append(
                f"| {_md(_first(evidence, 'evidence_id', 'id', default='Not supplied'))} | "
                f"{_md(_first(evidence, 'source_type', default='Not supplied'))} | "
                f"{_md(_first(evidence, 'system', default='Not supplied'))} | "
                f"{_md(_first(evidence, 'observed_at', default='Not supplied'))} | "
                f"{_md(_first(evidence, 'assurance', default='E0'))} | "
                f"{_md(_first(evidence, 'population_coverage', default='Not supplied'))} | "
                f"{_md(_first(evidence, 'notes', default='None supplied'))} |"
            )
    else:
        lines.append("| None supplied | — | — | — | E0 | — | Assessment payload contained no evidence inventory |")

    exceptions = [
        _mapping(item)
        for item in _sequence(_first(assessment, "exceptions", default=[]))
    ]
    lines.extend(
        [
            "",
            "## Applicability, equivalent-control, and waiver decisions",
            "",
            "| Decision | Type | Controls | Status | Risk owner | Approver | Expires | Rationale |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if exceptions:
        for decision in exceptions:
            lines.append(
                f"| {_md(_first(decision, 'decision_id', 'exception_id', 'id', default='Not supplied'))} | "
                f"{_md(_first(decision, 'type', default='Not supplied'))} | "
                f"{_md(_first(decision, 'control_ids', 'controls', default='Not supplied'))} | "
                f"{_md(_first(decision, 'status', default='Not supplied'))} | "
                f"{_md(_first(decision, 'risk_owner', default='Not supplied'))} | "
                f"{_md(_first(decision, 'approver', default='Not supplied'))} | "
                f"{_md(_first(decision, 'expires_at', 'expiry', default='Not supplied'))} | "
                f"{_md(_first(decision, 'rationale', default='Not supplied'))} |"
            )
    else:
        lines.append("| None supplied | — | — | — | — | — | — | — |")

    findings = [_mapping(item) for item in _sequence(_first(assessment, "findings", default=[]))]
    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| Finding | Priority | Control | Condition | Recommended outcome |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if findings:
        for finding in findings:
            lines.append(
                f"| {_md(_first(finding, 'finding_id', 'id', default='Not supplied'))} | "
                f"{_md(_first(finding, 'priority', default='Not supplied'))} | "
                f"{_md(_first(finding, 'control_id', 'control', default='Not supplied'))} | "
                f"{_md(_first(finding, 'condition', 'rationale', default='Not supplied'))} | "
                f"{_md(_first(finding, 'remediation', 'recommended_outcome', default='Not supplied'))} |"
            )
    else:
        lines.append("| None supplied | — | — | — | — |")

    lines.extend(["", "## Evidence limitations", ""])
    if limitations:
        lines.extend(f"- {_inline(item)}" for item in limitations)
    else:
        lines.append("- No additional limitation was supplied by the assessment.")

    actions = _sequence(leadership["top_actions"])
    lines.extend(["", f"## Priority improvement plan — next {len(actions)}", ""])
    if actions:
        lines.extend(
            [
                "| Order | Action | Accountable role | Completion evidence | Standing impact |",
                "| ---: | --- | --- | --- | --- |",
            ]
        )
        for action in actions:
            item = _mapping(action)
            lines.append(
                f"| {_md(item['rank'])} | {_md(item['action'])} | {_md(item['owner_role'])} | "
                f"{_md(item['expected_evidence_or_outcome'])} | {_md(item['standing_impact'])} |"
            )
    else:
        lines.append("No corrective action was generated from the supplied applicable control results.")

    lines.extend(
        [
            "",
            "## Delivery outcome panel — informative only",
            "",
            "Delivery outcome measures are reported separately. They do not change the 0–100 score, grade, maturity, assurance, or foundational results.",
            "",
        ]
    )
    if dora.get("available") and dora.get("metrics"):
        lines.extend(["| Measure | Value | Window | Limitation |", "| --- | --- | --- | --- |"])
        for metric in _sequence(dora.get("metrics")):
            item = _mapping(metric)
            lines.append(
                f"| {_md(item.get('name'))} | {_md(item.get('value'))} | "
                f"{_md(item.get('window'))} | {_md(item.get('limitation'))} |"
            )
        if dora.get("context"):
            lines.extend(["", f"**Context:** {_inline(dora.get('context'))}"])
        if dora.get("limitations"):
            lines.extend(["", "**Limitations:**"])
            lines.extend(
                f"- {_inline(item)}" for item in _sequence(dora.get("limitations"))
            )
    else:
        lines.append(_inline(dora.get("reason"), default="No delivery outcome data was supplied."))

    lines.extend(
        [
            "",
            "## Report contract",
            "",
            f"- Renderer schema: {REPORT_SCHEMA_VERSION}",
            f"- Assessment standard: {_inline(standard_version)} (provisional)",
            "- Ratings and scores are preserved from the assessment payload; this renderer does not rescore the repository.",
            "- The controlled action map covers all 35 controls in standard 0.1.0-draft.",
            "- Leadership actions are selected only from applicable controls rated Partially met, Unmet, or Unknown.",
            "- At most seven distinct actions are reported, ordered by foundational effect, finding priority, gap state, and catalog risk order.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_reports(
    assessment: Mapping[str, Any], output_dir: str | Path
) -> dict[str, Path]:
    """Write the three stable report artifacts and return their paths."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "health_assessment": destination / "health-assessment.md",
        "leadership_summary_markdown": destination / "leadership-summary.md",
        "leadership_summary_json": destination / "leadership-summary.json",
    }
    leadership = build_leadership_summary(assessment)
    paths["health_assessment"].write_text(
        render_health_assessment(assessment), encoding="utf-8"
    )
    paths["leadership_summary_markdown"].write_text(
        render_leadership_summary(assessment), encoding="utf-8"
    )
    paths["leadership_summary_json"].write_text(
        json.dumps(leadership, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render detailed and leadership repository-health reports"
    )
    parser.add_argument(
        "--assessment",
        "--input",
        dest="assessment",
        required=True,
        type=Path,
        help="Path to the structured assessment JSON",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for the three report artifacts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        assessment = load_assessment(args.assessment)
        paths = write_reports(assessment, args.output_dir)
    except ReportInputError as exc:
        print(f"reporting error: {exc}", file=sys.stderr)
        return 2
    manifest = {key: str(value) for key, value in paths.items()}
    print(json.dumps(manifest, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
