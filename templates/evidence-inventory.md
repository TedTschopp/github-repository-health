# Repository Health Evidence Inventory

> Template version 0.1.0-draft — provisional. Evidence supports an assessment at a stated cutoff; it does not prove conditions outside its scope, time window, or provenance.

## Inventory identity

| Field | Value |
| --- | --- |
| Assessment ID | `{{ID}}` |
| Repository | `{{owner/repository}}` |
| Standard version | `0.1.0-draft` |
| Evidence cutoff | `{{date/time/timezone}}` |
| Collector(s) | `{{names/roles}}` |
| Storage/reference location | `{{approved location}}` |
| Access/redaction constraints | `{{constraints}}` |

## Evidence register

Use one row per distinct item or query result. Preserve enough detail for a second assessor to retrieve or reproduce it without copying secrets or sensitive payloads into the assessment.

| Evidence ID | Control/gate | Claim supported | Source type and authoritative system | Stable path/query/reference | Scope and population coverage | Observed at | Period start/end | Freshness days and rule/result | Provenance/collector | Level E0–E4 | Access/redaction | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `{{EV-001}}` | `{{ID}}` | `{{precise claim}}` | `{{repository/config/CI/release/deploy/etc.}}` | `{{reference}}` | `{{branch/component/environment/unit; numerator/denominator or coverage}}` | `{{timestamp}}` | `{{from–to/current snapshot}}` | `{{age; rule; Fresh/Stale}}` | `{{who/how}}` | `{{E0–E4}}` | `{{classification}}` | `{{limitations}}` |

Suggested source types include:

- repository content and immutable revisions;
- host settings, rulesets, permissions, and audit records;
- CI definitions and execution history;
- test, quality, security, and dependency results;
- artifact registry, signing, attestation, SBOM, and release records;
- deployment, environment, GitOps reconciliation, and rollback records;
- ownership, lifecycle, support, and exception records; and
- incident or delivery-outcome systems used only for applicable controls or the separate DORA panel.

## Control-to-evidence coverage

| Control/gate | Applicability | Conformance | Minimum evidence | Evidence IDs | Assigned level | Fresh/current? | Coverage limitation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{{ID}}` | `{{Applicable/N/A pending/N/A approved}}` | `{{Met/Partially met/Unmet/Unknown/N/A}}` | `{{level/source/window}}` | `{{IDs/None}}` | `{{E0–E4/N/A}}` | `{{Yes/No}}` | `{{scope/gap}}` |

For E0, create a row that states what was sought, which source was unavailable or insufficient, and whether the cause was missing practice, retention, access, or assessment scope. Do not leave an unexplained blank.

## Production/release identity ledger

Repeat rows for every independently released unit in a monorepo.

| Production/published unit | Current identity | Artifact/state | Source revision | Reachable from Main? | Build/release evidence | Deployment/publication evidence | Gate effect |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{{service/package/environment}}` | `{{version/digest/SHA/state ID}}` | `{{reference}}` | `{{immutable revision}}` | `{{Yes/No/Unknown}}` | `{{EV IDs}}` | `{{EV IDs}}` | `{{G-02/G-04 result}}` |

## Relevant-event coverage

| Control | Normal window | Events in window | Extended low-activity window used? | Events inspected | Conclusion |
| --- | --- | ---: | --- | --- | --- |
| `{{ID}}` | `{{e.g., W90}}` | `{{n}}` | `{{No or W365; Low Sample if fewer than five remain}}` | `{{IDs/dates}}` | `{{evidence level and limitation}}` |

Low event count is not itself a failure. Record whether the repository is stable and low activity, newly created, inactive without declaration, or unable to retain evidence.

## Integrity and handling checks

- [ ] Evidence cutoff and timezone are explicit.
- [ ] Mutable UI/configuration snapshots record capture time and collector.
- [ ] Immutable revisions, run IDs, release IDs, or query parameters are used where available.
- [ ] Scope covers every claimed branch, component, environment, and production unit.
- [ ] Secrets, tokens, personal data, and sensitive logs are referenced or redacted rather than copied.
- [ ] Access failures and stale evidence are recorded as limitations, not silently inferred.
- [ ] Conflicting evidence is retained and explained.
- [ ] A second assessor can reproduce the claim from the reference or understand why not.

## Evidence-level distribution

| E0 | E1 | E2 | E3 | E4 | N/A | Applicable total | Assurance calculation |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `{{n}}` | `{{n}}` | `{{n}}` | `{{n}}` | `{{n}}` | `{{n}}` | `{{n}}` | `{{formula and result}}` |
