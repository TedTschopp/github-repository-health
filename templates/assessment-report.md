# Repository Health Assessment Report

> Template version 0.1.0-draft — provisional. Use with Repository Health Standard 0.1.0-draft and [Scoring, Assurance, and Exceptions](../docs/scoring-assurance-exceptions.md). Replace every placeholder; do not publish a score without the evidence and calculation sections.

## Assessment identity

| Field | Value |
| --- | --- |
| Repository | `{{owner/repository}}` |
| Repository URL | `{{URL}}` |
| Authoritative status | `{{canonical/mirror/fork/etc.; evidence}}` |
| Assessment ID | `{{stable ID}}` |
| Standard version | `0.1.0-draft` |
| Assessment date | `{{YYYY-MM-DD}}` |
| Evidence cutoff | `{{YYYY-MM-DD HH:MM timezone}}` |
| Next review | `{{YYYY-MM-DD}}` |
| Assessor(s) | `{{names/roles}}` |
| Repository owner | `{{name/role}}` |
| Scope | `{{repository, components, branches, environments, production units}}` |
| Exclusions | `{{explicit exclusions and rationale}}` |

## Classification

| Field | Result | Confidence/evidence |
| --- | --- | --- |
| Repository type | `{{classification}}` | `{{High/Moderate/Low; worksheet reference}}` |
| Workflow profile | `{{canonical profile/Unclassified}}` | `{{High/Moderate/Low; declared/observed divergence}}` |
| Risk tier | `{{Baseline/Elevated/Critical}}` | `{{assignment rationale}}` |
| Main/canonical integration line | `{{ref}}` | `{{evidence IDs}}` |
| Production/published identity | `{{identity or None}}` | `{{evidence IDs}}` |
| Lifecycle state | `{{Active/Stable-supported/Experimental/Mirrored/Archived/Retired/Unknown}}` | `{{evidence IDs}}` |

Reference: [Methodology Worksheet](methodology-worksheet.md) `{{worksheet ID/link}}`.

## Result at a glance

| Result | Value |
| --- | --- |
| Raw score | `{{0.0–100.0}}` |
| Calculated result | `{{letter}} / {{maturity}}` |
| Gate cap | `{{None or 69.0/D/M1; triggering gate IDs}}` |
| **Effective result** | **`{{capped numeric score}} / {{letter}} / {{maturity}}`** |
| Assurance | `{{index}} / {{High/Moderate/Low}}` |
| Applicable dimensions | `{{n}} of 8` |
| Applicable controls | `{{n}} of {{catalog total}}` |
| Unknown controls | `{{n}}` |
| Open exceptions | `{{n; nearest expiration}}` |

### Executive interpretation

`{{Two to four sentences stating what the result establishes, the most material gate/dimension issues, and evidence limitations. Do not restate the score as certainty.}}`

## Foundational gates

| Gate | Outcome | Conformance | Evidence level | Evidence IDs | Exception | Cap effect |
| --- | --- | --- | --- | --- | --- | --- |
| G-01 — Main buildable | `{{Pass/Fail/Unknown/N/A}}` | `{{Met/Partially met/Unmet/Unknown/N/A}}` | `{{E0–E4/N/A}}` | `{{IDs}}` | `{{ID/None}}` | `{{None/D cap}}` |
| G-02 — production/published identity traceable | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| G-03 — controlled auditable path to Main | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| G-04 — production-critical references protected | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |

For a multi-production-unit repository, add one row per unit beneath each gate and report the least healthy applicable outcome in the gate row.

## Reproducible score calculation

| Code | Dimension | Conformance points | Applicable controls | Dimension score | Weight after N/A normalization | Weighted contribution | Principal evidence/findings |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| SPI | Source-to-production integrity | `{{sum}}` | `{{n}}` | `{{sum/n}}` | `{{%}}` | `{{score*weight}}` | `{{IDs}}` |
| BTC | Build, test, and CI health | `{{sum}}` | `{{n}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| CGD | Change governance and branch discipline | `{{sum}}` | `{{n}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| SSC | Security and software-supply-chain health | `{{sum}}` | `{{n}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| OWM | Ownership and maintainability | `{{sum}}` | `{{n}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| DCR | Documentation and contributor readiness | `{{sum}}` | `{{n}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| RRO | Release, rollback, and operational readiness | `{{sum}}` | `{{n}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| RLP | Repository lifecycle and portfolio hygiene | `{{sum}}` | `{{n}}` | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| **Raw total** |  |  |  |  | **100%** | **`{{0.0–100.0}}`** |  |
| **Effective/capped total** |  |  |  |  |  | **`{{min(raw, 69.0) when a gate caps; otherwise raw}}`** | `{{gate IDs/No cap}}` |

Calculation notes:

- `{{List control weights if a later standard version defines any; 0.1.0-draft uses equal control weight within dimensions.}}`
- `{{List N/A dimensions and show how remaining dimension weights were normalized equally.}}`
- `{{State unrounded raw score and the band/cap calculation.}}`

## Assurance and evidence coverage

| E0 | E1 | E2 | E3 | E4 | Applicable controls | Assurance calculation | Label |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `{{n}}` | `{{n}}` | `{{n}}` | `{{n}}` | `{{n}}` | `{{n}}` | `{{(0*E0 + 25*E1 + 50*E2 + 75*E3 + 100*E4)/n}}` | `{{High/Moderate/Low}}` |

Evidence inventory: `{{link/reference to evidence-inventory instance}}`.

### Unknowns and limitations

| Control/scope | Why unknown or limited | Score/assurance effect | Evidence or access needed | Owner/date |
| --- | --- | --- | --- | --- |
| `{{ID}}` | `{{reason}}` | `{{0 points, E0; gate cap if applicable}}` | `{{needed evidence}}` | `{{owner/date}}` |

## N/A and equivalent-control decisions

| Control/dimension | Disposition | Classification rationale | Evidence | Approver/date | Reassessment trigger |
| --- | --- | --- | --- | --- | --- |
| `{{ID}}` | `{{N/A/Equivalent}}` | `{{why}}` | `{{IDs}}` | `{{name/date}}` | `{{date/event}}` |

## Findings and remediation

| Finding | Priority | Control/gate | Condition | Risk/outcome | Owner | Target | Exception |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{{F-001}}` | `{{P0–P3}}` | `{{ID}}` | `{{concise fact}}` | `{{consequence}}` | `{{role}}` | `{{date}}` | `{{ID/None}}` |

Detailed register: `{{link/reference to findings-and-remediation instance}}`.

## Exceptions

| Exception | Type | Control | Status | Risk acceptor | Approved | Expires | Compensating control | Score/cap effect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `{{EX-001}}` | `{{Temporary waiver}}` | `{{ID}}` | `{{Active/etc.}}` | `{{role}}` | `{{date}}` | `{{date}}` | `{{summary}}` | `{{underlying rating retained}}` |

## DORA outcome panel — separate from repository score

| Product/service | Measure | Value | Formula/source | Window/coverage | Limitation/trend |
| --- | --- | --- | --- | --- | --- |
| `{{scope}}` | Change lead time | `{{value/N/A/Unknown}}` | `{{source}}` | `{{window}}` | `{{note}}` |
| `{{scope}}` | Deployment frequency | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| `{{scope}}` | Failed deployment recovery time | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| `{{scope}}` | Change fail rate | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |
| `{{scope}}` | Deployment rework rate | `{{...}}` | `{{...}}` | `{{...}}` | `{{...}}` |

These values are not included in the 0–100 score or gate result.

## Review and sign-off

| Role | Name | Disposition | Date | Notes |
| --- | --- | --- | --- | --- |
| Assessor 1 | `{{name}}` | `{{Signed}}` | `{{date}}` | `{{notes}}` |
| Assessor 2/pilot | `{{name/N/A}}` | `{{Signed/N/A}}` | `{{date}}` | `{{notes}}` |
| Repository owner | `{{name}}` | `{{Acknowledged/Response attached}}` | `{{date}}` | `{{notes}}` |
| Adjudication chair | `{{name/N/A}}` | `{{Final/N/A}}` | `{{date}}` | `{{precedent IDs}}` |

Repository-owner acknowledgement confirms receipt and factual response; it is not approval authority over the rating.
