# Documentation Artifact Schemas

**Standard version:** 0.1.0-draft

These controlled supporting schemas are the public interfaces among the standard, catalog, workbook, assessment reports, supporting automation, and future versions. They describe required fields; they do not grant a collector permission to modify a repository or make the supporting automation normative. The [normative assessment set and precedence](repository-health-standard.md#normative-document-set-and-precedence) govern assessment outcomes.

## Control record

| Field | Required | Meaning |
| --- | --- | --- |
| `control_id` | Yes | Stable identifier using the dimension prefix and sequence. |
| `version` | Yes | Standard version in which this control text applies. |
| `title` | Yes | Short outcome-oriented name. |
| `dimension` | Yes | One of the eight canonical health dimensions. |
| `foundational_gate` | Yes | `G-01` through `G-04`, or `None`. |
| `minimum_risk_tier` | Yes | Baseline, Elevated, or Critical. |
| `applicability` | Yes | Repository types, lifecycle states, and deployable-unit conditions. |
| `requirement` | Yes | Normative MUST, SHOULD, or MAY statement. |
| `intent` | Yes | Risk or outcome addressed. |
| `acceptable_patterns` | Yes | Non-exclusive examples and equivalent-control considerations. |
| `required_evidence` | Yes | Evidence objects needed to assess the outcome. |
| `minimum_assurance` | Yes | Lowest E-level that can support `Met`. |
| `measurement_ids` | Yes | One or more metric IDs from the dictionary. |
| `threshold` | Yes | Conformance rule or explicit qualitative decision rule. |
| `unknown_treatment` | Yes | Consequence of absent or stale evidence. |
| `na_rule` | Yes | Conditions under which N/A is legitimate. |
| `exception_rule` | Yes | Whether equivalent control or temporary waiver is allowed. |
| `grade_effect` | Yes | Normal points, gate cap, or other documented consequence. |
| `remediation_outcome` | Yes | Desired state without prescribing a vendor tool. |
| `source_ids` | Yes | Pinned source-register references. |
| `owner` | Yes | Accountable standard domain owner. |
| `review_date` | Yes | Next review date in ISO 8601 form. |

## Measurement record

| Field | Required | Meaning |
| --- | --- | --- |
| `metric_id` | Yes | Stable metric identifier. |
| `name` | Yes | Human-readable measure name. |
| `question` | Yes | Decision the measure helps answer. |
| `formula` | Yes | Exact calculation or qualitative decision rule. |
| `numerator` / `denominator` | Conditional | Populations used for rate measures. |
| `unit` | Yes | Boolean, count, rate, duration, age, or ordinal state. |
| `observation_window` | Yes | Period or point-in-time rule. |
| `eligible_population` | Yes | Included and excluded events or objects. |
| `source_systems` | Yes | Permitted evidence origins. |
| `freshness` | Yes | Maximum acceptable evidence age. |
| `thresholds` | Yes | Met, Partially met, and Unmet boundaries by applicable tier. |
| `missing_data` | Yes | Unknown, N/A, or other defined behavior. |
| `aggregation` | Yes | Deployable-unit, repository, dimension, and portfolio rule. |
| `polarity` | Yes | Whether higher, lower, or exact-state is better. |
| `limitations` | Yes | Interpretation and gaming risks. |
| `source_ids` | Yes | Pinned source-register references. |

## Evidence record

| Field | Required | Meaning |
| --- | --- | --- |
| `evidence_id` | Yes | Assessment-local stable identifier. |
| `control_ids` | Yes | Controls supported or contradicted. |
| `source_type` | Yes | Git, host settings, CI, registry, deployment, security, operations, documentation, or attestation. |
| `system` | Yes | Named system of record. |
| `location` | Yes | Read-only link, immutable identifier, exported record, or precise description. |
| `observed_at` | Yes | When the assessor observed it. |
| `period_start` / `period_end` | Conditional | History covered by trend evidence. |
| `population_coverage` | Yes | Scope and denominator represented. |
| `freshness_days` | Yes | Age at assessment cutoff. |
| `assurance` | Yes | E0 through E4. |
| `collector` | Yes | Assessor or evidence provider. |
| `notes` | No | Limitations, contradictions, or redaction statement. |

Sensitive evidence should be referenced rather than copied into an assessment workbook.

## Assessment result

An issued result must contain:

- Assessment and standard version identifiers.
- Repository identity, authoritative status, lifecycle, type, risk tier, and deployable units.
- Main-role mapping and production-correspondence policy.
- Declared and observed methodology profiles, or `Unknown`/`Unclassified` with Low confidence when evidence is insufficient, plus axes and contradictions.
- Control-level applicability, conformance, assurance, evidence IDs, exceptions, and findings.
- Raw and capped score, letter, maturity, eight dimensions, gate results, and evidence coverage.
- Separate DORA outcome panel or a reason it is unavailable.
- Assessor, reviewer, evidence cutoff, issue date, next review, and provisional-status disclosure.

### Automated assessment extension

An assessment produced by the supporting evaluator uses schema version `1.0` and also records:

| Field | Required | Meaning |
| --- | --- | --- |
| `automation.engine_version` | Yes | Version of the evaluator implementation. |
| `automation.catalog_sha256` | Yes | Digest of the exact catalog parsed for the result. |
| `automation.config_sha256` | Yes | Digest of the repository declaration used for the result. |
| `automation.collector_mode` | Yes | `local-only` or `local+github`, without implying that every requested endpoint was accessible. |
| `automation.read_only_collection` | Yes | Must be `true` for this diagnostic action. |
| `automation.repository_owned_code_executed` | Yes | Must be `false`; existing CI supplies build and test evidence. |
| `facts.local` | Yes | Source-state and bounded working-tree observations, including Main resolution and cleanliness. |
| `facts.github` | Yes | Endpoint status, visible host evidence, and explicit collection gaps. |
| `controls` | Yes | Exactly one result for each control in the matching catalog version. |
| `dimensions` | Yes | Score, applicability coverage, and evidence coverage for each of the eight dimensions. |
| `gates` | Yes | Exactly G-01 through G-04 with status, assurance, control, and rationale. |
| `score` | Yes | Raw/effective score and grade plus active and numeric cap indicators. |
| `assurance` | Yes | Assurance index, label, and E0–E4 distribution. |
| `limitations` | Yes | Collection, review, calibration, and evidence limitations that qualify interpretation. |
| `dora.informative_only` | Yes | Must be `true`; DORA data cannot affect the repository-control result. |

The evaluator must retain unavailable or forbidden GitHub endpoint results as collection gaps. A `403`, `404`, timeout, or missing endpoint response cannot establish either conformance or nonconformance unless another acceptable record establishes the outcome.

## Leadership summary record

The supporting renderer emits `repository-health-leadership-summary/v1`. It is a compact view, not a replacement for the full assessment JSON.

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | Yes | `repository-health-leadership-summary/v1`. |
| `assessment_schema_version` | Yes | Schema version of the source assessment. |
| `standard_version` / `assessment_id` / `generated_at` | Yes | Traceability to the source result. |
| `repository` | Yes | Repository identity, owner, type, lifecycle, risk tier, Main ref, and assessed revision when available. |
| `standing` | Yes | Raw/effective result, assurance, and foundational-cap state. |
| `evidence` | Yes | Unknown-control count and limitations. |
| `top_actions` | Yes | Zero through seven ordered, evidence-based actions derived only from applicable Partially met, Unmet, or Unknown controls. |
| `dora` | Yes | Separate informative-only delivery outcome view or reason unavailable. |
| `disclosures` | Yes | Provisional-calibration and DORA-separation statements. |

Each action contains a rank, action/control/gate identifiers, plain-language title and action, accountable role, reason, completion evidence, standing impact, assessment basis, ordering rationale, current rating, and assurance. If fewer than seven genuine gaps exist, the list is shorter; the renderer must not invent work to fill the list.

## Stable automated report set

A successful action run writes these stable names in its configured output directory:

- `repository-health-assessment.json` — full machine-readable assessment;
- `health-assessment.md` — detailed evidence-facing report;
- `leadership-summary.md` — nontechnical standing and ordered action plan; and
- `leadership-summary.json` — compact leadership exchange record.

Adding an optional JSON field is backward-compatible. Changing a filename, required field, field meaning, enum, calculation, or prioritization contract requires a versioned migration note and regression tests.

## Release identity record

The revision-bound release builder emits `RH-RELEASE-IDENTITY-1.0` alongside the source package and SPDX SBOM. The record is evidence about a published unit; it does not itself prove that the referenced GitHub Release or attestation exists.

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | Yes | `RH-RELEASE-IDENTITY-1.0`. |
| `package_name` / `version` / `tag` | Yes | Stable unit name and immutable version identity. |
| `source_repository` | Yes | Canonical HTTPS repository URL. |
| `source_ref` | Yes | Protected immutable version-tag ref. |
| `source_sha` | Yes | Exact 40-character source commit reachable from Main. |
| `source_commit_time` | Yes | Source commit time used for reproducible metadata. |
| `standard_version` | Yes | Controlled version read from the exact tagged `.github/repository-health.toml`. |
| `production_correspondence` | Yes | Declared correspondence contract; initially `Releasable-Main`. |
| `file_count` | Yes | Complete tracked-file population at `source_sha`. |
| `artifacts` | Yes | Source archive and SBOM names, roles, media types, and SHA-256 digests. |
| `builder` | Yes | Builder version, archive format, and exact Git and Python toolchain observed for repeatability analysis. |

The stable release set is:

- `github-repository-health-<tag>.tar.gz` — revision-bound source package;
- `github-repository-health-<tag>.spdx.json` — SPDX 2.3 file inventory;
- `github-repository-health-<tag>.source.json` — source and artifact identity;
- `SHA256SUMS` — digest manifest for the three generated records; and
- the GitHub artifact-attestation bundle returned by the pinned attestation action.

Changing these names, required fields, digest semantics, or correspondence meaning requires a versioned migration note and regression tests.

## Production identity record

The repository-level `.github/repository-health-production.json` file uses schema `RH-PRODUCTION-IDENTITY-1.0`. It is a versioned resolver and expected-identity record, not self-validating production proof.

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` / `standard_version` | Yes | Record contract and controlled standard versions. |
| `repository` | Yes | Canonical GitHub `owner/name` identity. |
| `units` | Yes | Nonempty array of independently published or deployed units. |
| `unit_id` / `kind` / `correspondence` | Per unit | Stable unit identity, resolver kind, and canonical production-correspondence contract. |
| `selection` | Per unit | Deterministic selection rule, including tag derivation and whether prerelease, draft, or mutable latest aliases are permitted. |
| `current` | Per unit | Expected release, tag object, source revision, publication state, artifact digests, and attestation identities. |
| `validation` | Per unit | Required exact-revision checks, Main-ancestry rule, intervening-revision rule, and incomplete-history treatment. |
| `limitations` | Per unit | Known contradictions or assurance boundaries that automation and reports must retain. |

Automation MUST resolve the live target and compare it with this record. Missing APIs, incomplete Main/check history, stale selectors, or identity conflicts remain Unknown or Fail under the measurement dictionary; committed JSON alone cannot pass G-02.

## Exception record

| Field | Required | Meaning |
| --- | --- | --- |
| `exception_id` | Yes | Stable identifier. |
| `type` | Yes | N/A determination, equivalent control, or temporary waiver. |
| `control_ids` | Yes | Requirements affected. |
| `scope` | Yes | Repository, deployable unit, branch/ref, or environment. |
| `risk_owner` | Yes | Accountable owner accepting residual risk. |
| `rationale` | Yes | Why direct conformance is not presently achieved. |
| `compensating_control` | Conditional | Alternate outcome or risk reduction. |
| `approver` | Yes | Authorized decision-maker. |
| `approved_at` | Yes | Approval date. |
| `expires_at` | Conditional | Mandatory for temporary waivers. |
| `review_date` | Yes | Next review date. |
| `status` | Yes | Proposed, active, expired, revoked, or closed. |

## Finding record

A finding contains a stable ID, affected controls and deployable units, evidence, observed condition, expected outcome, risk statement, priority, recommended outcome, owner, target date, exception link, status, and closure evidence.

## Compatibility rule

Adding an optional field is backward-compatible. Renaming a field, changing its meaning, removing it, changing a calculation, or changing an applicability rule requires a versioned migration note and scoring regression review.
