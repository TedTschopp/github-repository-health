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

## Automated observation bundle

The GitHub collector emits `RH-GITHUB-OBSERVATIONS-1.0`. The bundle is a read-only evidence exchange, not a score or control disposition. It contains the repository identity, exact Main subject SHA, observed time, applicable unit IDs, named observation groups, and explicit bundle gaps. Each group records a stable evidence ID, source, subject SHA, eligible-population completeness, pagination/request metadata, raw source records, and its own gaps. A partial group retains records already observed but cannot establish a passing metric.

Every observation and assessment timestamp must be an offset-aware ISO 8601 instant. An offset-free, invalid, or future observation timestamp is unusable for freshness and therefore yields Unknown; a caller-supplied `fresh` flag cannot override that check.

The normalizer adds purpose-built metric groups without deleting the raw groups. Its `RH-NORMALIZATION-1.0` summary records conflicts, limitations, and the invariant that the assessor did not invoke assessed build, test, deploy, hook, or application code. A missing field, page, required classification, production identity, exact-SHA binding, or source-system permission remains Unknown; it is not converted into an empty population.

## Workflow evidence statement

The bounded evidence producer emits `repository-health-evidence-statement/v1` as canonical JSON plus a strict single-file SHA-256 manifest. The statement binds an explicit caller-supplied `success`, `failure`, or `unknown` result to the exact repository, controlled `unit_id`, source ref/SHA and subject digests, workflow ref/SHA, run ID/attempt, offset-aware timestamp, evidence kind/categories, artifact digests, and source evidence IDs. Its content-addressed `statement_id` supports exact-duplicate rejection.

The producer does not run or infer the assessed work. Its `producer_invoked_assessed_code: false` field applies only to the producer and must never be presented as a claim that the whole workflow job ran no repository code; the caller's outcome-producing steps normally do run such code. Successful release/deployment statements require artifact digests, all statements require a subject digest and source evidence IDs, and validation rejects duplicate keys/identifiers, non-finite values, ambiguous refs, future timestamps, and caller-known identity mismatches. The complete trust boundary and collector contract are defined in the [Evidence Producer](evidence-producer.md). The assessor can retain independently verified statements in its evidence inventory, but no producer statement changes a measurement, control, gate, or score until a controlled metric-specific resolver consumes it; until then, producer outcomes do not affect an assessment result.

## Workflow evidence policy

The repository-level `.github/repository-health-evidence-policy.json` file uses `RH-EVIDENCE-POLICY-1.0`. The assessor reads its exact bytes from the assessed Main commit. A working-tree file, feature-branch version, API copy without a Git-object binding, or policy whose repository or units disagree with the assessment is unusable.

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | Yes | Exactly `RH-EVIDENCE-POLICY-1.0`. |
| `repository` | Yes | Exact GitHub `owner/name` being assessed. |
| `units` | Yes | Nonempty, unique subset of the deployable or publishable units declared by the repository configuration. |
| `unit_id` | Per unit | Controlled unit to which every nested statement policy applies. |
| `statements` | Per unit | Nonempty list with at most one policy for each of `validation`, `security`, `release`, and `deployment`. |
| `categories` | Per statement | Sorted, unique, nonempty controlled category identifiers; the match is exact rather than a subset test. |
| `workflow_path` | Per statement | Safe repository-relative workflow path under `.github/workflows/`. |
| `subject_source` | Per statement | `assessed-main` or `production-unit`. |
| `events` | Per statement | Sorted, unique subset of `push`, `workflow_dispatch`, `schedule`, `release`, and `deployment`. |
| `selection` | Per statement | Exactly `latest-completed-exact-subject`. |

The validated in-memory policy adds a `_source` binding containing the exact Main SHA, repository path, and SHA-256 of the policy bytes. `_source` is assessor-generated provenance and is not a caller-supplied field in the committed schema.

## Actions run population and evidence selection

`RH-ACTIONS-RUN-POPULATION-1.0` states what the Actions run collection completely covers. It has exactly `schema_version`, `scope`, `branch_ref`, and `subjects`. The scheduled Actions history collector currently emits `scope: branch-window`, the full Main ref, and an empty `subjects` array. This population can support an `assessed-main` policy. A `production-unit` policy requires a separately collected `scope: exact-subjects` population, `branch_ref: null`, and an exact `{sha, ref}` entry; a Main-only branch window cannot prove that a production tag or other production ref was completely searched.

The selector emits `RH-EVIDENCE-POLICY-SELECTION-1.0`. It retains the policy source binding, repository and Main SHA, selection state and completeness, population completeness, explicit eligible run-to-unit mapping, derived category policy, selected run facts, and every gap. `latest-completed-exact-subject` considers only terminal runs whose subject SHA, controlled workflow identity, permitted event, run attempt, and subject ref agree. The newest terminal timestamp must identify exactly one run. Ties, run/unit artifact collisions, missing subjects, an incomplete population, or no eligible terminal run yield Unknown. Partial selections may remain visible for diagnosis, but do not make the overall selection complete.

## Evidence artifact collection and internal verification

The bounded collector emits `RH-EVIDENCE-ARTIFACTS-1.0`. Its eligible population is an explicit run-to-unit mapping, and the only accepted artifact name is `repository-health-evidence--<unit_id>`. Candidate ZIPs, byte digests, package validation, run/source joins, category-policy checks, duplicate/conflict analysis, limits, and gaps remain visible beneath the bundle state.

During the trusted collector invocation, an internal projection emits `RH-EVIDENCE-STATEMENT-VERIFICATION-1.0` for a candidate only after at least one authoritative source record is resolved. It binds the statement ID, repository, unit, source SHA, population completeness, matched authoritative source IDs, and separate source, result, artifact, and category-policy booleans. Its state is `verified`, `unknown`, or `conflict`. The integrated assessor does not accept the projection from repository JSON, producer ZIP content, configuration, or a caller-supplied report; serializing the same fields cannot authenticate them. The assessment may expose this collector-owned projection for audit and may label an independently verified evidence-inventory record E3, while the collector bundle still declares `assurance_assigned: false` and `score_mapping_applied: false`. Evidence assurance at that layer is not control conformance.

GitHub deployment evidence uses the same exact `repository-health-deployment-artifact-binding/v1` payload contract as the delivery collector: top-level `schema_version`, `unit_id`, and `artifact` fields only, with the nested artifact containing exactly `reference` and `sha256`. The evidence collector requires the unit and single statement digest to match, preserves the controlled reference for the later production-selector join, and rejects the older parallel `artifact_digests` payload as Unknown.

## Automated measurement result

Every calculated result uses `RH-METRIC-RESULT-1.0` and metric rules `RH-METRICS-0.1`. Required fields are:

| Field | Required | Meaning |
| --- | --- | --- |
| `metric_id` / `metric_version` / `threshold_version` | Yes | Exact measure and controlled calculation contracts. |
| `repository` / `unit_id` / `main_sha` | Yes | Repository, optional deployable-unit scope, and assessed Main revision. |
| `state` / `band` | Yes | `measured`, `no_events`, `unknown`, or `n_a`; measured results use Pass, Concern, or Fail. |
| `value` / `unit` / `numerator` / `denominator` | Conditional | Calculated value and auditable populations when defined. |
| `components` | Yes | Intermediate values, including per-unit results for repository aggregation. |
| `sample_size` / `sample_class` | Yes | Standard, Low Sample, No Events, Unknown, or applicable equivalent. |
| `window` / `coverage` / `freshness` | Yes | Required period, population completeness, and evidence age. |
| `assurance` | Yes | E0 through E4 supported by the source evidence. |
| `evidence_ids` / `observation_ids` / `source_codes` | Yes | Traceability back to source observations. |
| `limitations` / `conflicts` / `exceptions` | Yes | Qualification retained beneath the aggregate result. |

Repository aggregation uses the documented worst applicable unit. Any applicable Unknown unit makes the repository result Unknown. A No Events trend can carry a current metric's band only where the measurement dictionary explicitly allows it and the result names that current metric.

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
| `automation.observation_schema_version` | Yes | Exact normalized observation contract. |
| `automation.metric_schema_version` / `automation.metric_version` | Yes | Result exchange and calculation-rule versions. |
| `automation.catalog_sha256` | Yes | Digest of the exact catalog parsed for the result. |
| `automation.config_sha256` | Yes | Digest of the repository declaration used for the result. |
| `automation.collector_mode` | Yes | `local-only` or `local+github`, without implying that every requested endpoint was accessible. |
| `automation.read_only_collection` | Yes | Must be `true` for this diagnostic action. |
| `automation.assessed_repository_build_code_executed` | Yes | Must be `false`; the assessor may run its own pinned engine, but it does not execute the assessed repository's build, test, deploy, hook, or application code. Existing CI supplies that evidence. |
| `facts.local` | Yes | Source-state and bounded working-tree observations, including Main resolution and cleanliness. |
| `facts.github` | Yes | Endpoint status, visible host evidence, and explicit collection gaps. |
| `measurements` | Yes | One repository result for every implemented metric plus unit results when units are declared. |
| `controls` | Yes | Exactly one result for each control in the matching catalog version. |
| `dimensions` | Yes | Score, applicability coverage, and evidence coverage for each of the eight dimensions. |
| `gates` | Yes | Exactly G-01 through G-04 with status, assurance, control, and rationale. |
| `score` | Yes | Raw/effective score and grade plus active and numeric cap indicators. |
| `assurance` | Yes | Assurance index, label, and E0–E4 distribution. |
| `limitations` | Yes | Collection, review, calibration, and evidence limitations that qualify interpretation. |
| `dora.informative_only` | Yes | Must be `true`; DORA data cannot affect the repository-control result. |

The evaluator must retain unavailable or forbidden GitHub endpoint results as collection gaps. A `403`, `404`, timeout, or missing endpoint response cannot establish either conformance or nonconformance unless another acceptable record establishes the outcome.

Foundational gates are derived only from the four current-state metrics: G-01 from `M-SPI-01`, G-02 from `M-SPI-02S`, G-03 from `M-CGD-01`, and G-04 from `M-CGD-02`. A Pass band below E3 remains an Unknown gate. Trend metrics may lower the linked control result but cannot turn a failing or Unknown current-state gate into Pass.

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
| `production_correspondence` | Yes | Non-Unknown correspondence contract read from the exact tagged repository configuration. |
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

## Durable evidence snapshot

The isolated publisher writes `repository-health-evidence-snapshot/v1` records on the dedicated `repository-health-evidence` branch. Each immutable snapshot embeds the assessment, controlled report digests and sizes, source/workflow/run provenance, its controlled branch path, and the SHA-256 digest of the preceding snapshot's exact bytes. `repository-health-evidence-latest/v1` identifies the chain tip and repeats its exact digest. Timestamps and assessment IDs must increase, repository identity cannot change within a chain, and a publisher update uses a non-force ref advance.

## Production identity record

The repository-level `.github/repository-health-production.json` file is read from exact Main and supports two schemas. Both are versioned selector and expected-identity records, not self-validating production proof. The full contracts and current integration boundary are in [Production Identity and Delivery Resolution](production-identity.md).

### Legacy release profile

`RH-PRODUCTION-IDENTITY-1.0` retains the standards repository's narrow GitHub Release contract unchanged.

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

### Generic per-unit profile

`RH-PRODUCTION-IDENTITY-2.0` has exactly `schema_version`, `standard_version`, `repository`, and `units`. Its units must exactly match the configured deployable-unit population. Every unit has exactly these common fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `unit_id` | Yes | Stable unit identity, unique within the repository. |
| `profile` | Yes | `application-github-deployment`, `package-github-release`, `gitops-production-ref`, `documentation-publication`, `approved-no-current-output`, or `archived-retired`. |
| `lifecycle` / `correspondence` | Yes | Type-appropriate lifecycle and `Exact-Main`, `Releasable-Main`, `Production-Ref`, or `N/A` contract. |
| `source_sha` | Yes | Exact lowercase Git revision for active profiles; `null` for governed inactive profiles. |
| `selector` | Yes | Profile-discriminated exact system-of-record identity; fields from another profile are rejected. |
| `validation` | Yes | Exact configured checks, Main-reachability and Main-ahead policy, independent system-of-record requirement, and `Unknown` treatment for incomplete proof. |
| `limitations` | Yes | String array retained in normalization and reporting. |

Active profiles select one exact deployment and artifact digest, release/tag and complete artifact population, GitOps ref/commit/path/content digest, or documentation publication and content digest. Inactive profiles record a governance decision, but the declaration cannot approve its own N/A or retirement result. The v2 validator and pure `RH-DELIVERY-RESOLUTION-1.0` resolver are implemented as groundwork. Until the assessor connects complete type-specific delivery populations, collector-owned statement or attestation bindings, Main ancestry, intervening-check facts, and metric mapping, generic units remain Unknown for G-02 rather than falling back to the declaration.

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
