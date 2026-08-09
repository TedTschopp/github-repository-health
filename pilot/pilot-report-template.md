# Repository Health Field Pilot Report Template

> Template version 0.1.0-draft — provisional. This is a blank reporting structure, not evidence that a pilot occurred or that the standard is calibrated.

Use this template only after following the locked protocol in [Governance and Pilot](../docs/governance-and-pilot.md). Preserve both independent assessments and adjudication records; do not replace them with this summary.

## Pilot identity and completion status

| Field | Value |
| --- | --- |
| Pilot ID | `{{ID}}` |
| Frozen standard version | `0.1.0-draft` |
| Pilot status | `{{Not started/In progress/Analysis complete/Pending decision/Closed}}` |
| Cohort lock date | `{{date}}` |
| Evidence cutoff | `{{date/time/timezone}}` |
| Assessment period | `{{start–end}}` |
| Pilot lead | `{{name/role}}` |
| Analysis owner | `{{name/role}}` |
| Architecture decision owner | `{{name/role}}` |
| Disclosure | `{{State that results remain provisional unless a calibrated successor is explicitly approved.}}` |

## Locked record inventory

| Required record | Expected | Actual | Complete? | Reference/limitation |
| --- | ---: | ---: | --- | --- |
| Real repositories in cohort | 12 | `{{n}}` | `{{Yes/No}}` | `{{reference}}` |
| Independent assessor submissions | 24 | `{{n}}` | `{{Yes/No}}` | `{{reference}}` |
| Adjudicated repository reports | 12 | `{{n}}` | `{{Yes/No}}` | `{{reference}}` |
| Repository-owner fact checks | 12 | `{{n}}` | `{{Yes/No}}` | `{{reference}}` |
| Evidence indexes | 24 | `{{n}}` | `{{Yes/No}}` | `{{reference}}` |
| Adjudication/precedent records | `{{expected}}` | `{{n}}` | `{{Yes/No}}` | `{{reference}}` |

## Cohort coverage

| Pilot ID | Canonical repository type(s) | Lifecycle | Canonical methodology profile or Unclassified | Risk tier | Assessor A | Assessor B | Pair locked? | Substitution/rationale |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `{{P01}}` | `{{type}}` | `{{state}}` | `{{profile}}` | `{{Baseline/Elevated/Critical}}` | `{{ID}}` | `{{ID}}` | `{{Yes/No}}` | `{{None/rationale}}` |

Summarize coverage gaps, substitutions, evidence-access differences, and whether the cohort includes at least three independently selected strong candidates and three known-problem candidates. Confirm that prior expectations remained blinded until both assessments were locked.

## Inter-rater and gate-detection results

| Measure | Numerator/data | Denominator | Calculation | Required result | Observed result | Pass? | Evidence |
| --- | ---: | ---: | --- | --- | --- | --- | --- |
| Exact applicable-control rating agreement | `{{agreed ratings}}` | `{{ratings compared}}` | `{{numerator/denominator × 100}}` | At least 85% | `{{%}}` | `{{Yes/No}}` | `{{reference}}` |
| Median absolute overall-score difference | `{{12 absolute deltas}}` | 12 pairs | `{{median method and value}}` | No more than 5.0 points | `{{points}}` | `{{Yes/No}}` | `{{reference}}` |
| Foundational-gate failure detection | `{{failures identified by both assessors}}` | `{{all seeded or adjudicated applicable failures}}` | `{{numerator/denominator × 100}}` | 100% | `{{%}}` | `{{Yes/No}}` | `{{reference}}` |
| Gate outcome agreement | `{{matching outcomes}}` | `{{applicable gate comparisons}}` | `{{numerator/denominator × 100}}` | Diagnostic | `{{%}}` | N/A | `{{reference}}` |
| Repository-type agreement | `{{matching classifications}}` | 12 pairs | `{{numerator/12 × 100}}` | Diagnostic | `{{%}}` | N/A | `{{reference}}` |
| Methodology-profile agreement | `{{matching classifications}}` | 12 pairs | `{{numerator/12 × 100}}` | Diagnostic | `{{%}}` | N/A | `{{reference}}` |

Report control-rating agreement with its numerator and denominator. Controls both assessors mark approved N/A are excluded; disagreement about N/A counts as disagreement.

## Exact acceptance-criteria decision

| # | Required acceptance criterion | Analysis/evidence | Result | Open issue/decision |
| ---: | --- | --- | --- | --- |
| 1 | Every supported methodology can achieve A when practiced well; field evidence or a matched reference case demonstrates attainability. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 2 | An unbuildable Main, unknown production identity, or uncontrolled production reference always triggers the grade cap; every applicable gate failure or unknown is visible. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 3 | Assessors agree on at least 85% of control ratings, median absolute overall-score difference is no more than 5 points, and both identify 100% of foundational-gate failures. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 4 | Every control specifies applicability, evidence, freshness, threshold, unknown handling, and exception handling; no assessor-created rule fills a missing field. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 5 | Stable low-activity repositories are not penalized merely for activity level. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 6 | Mirrors, archives, sandboxes, and non-deployable repositories receive type-appropriate assessments; legitimate N/A controls are not scored as failures. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 7 | Raw evidence and dimension results remain visible beneath the aggregate; score, assurance, gate cap, and N/A treatment are reproducible. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 8 | No methodology receives a systematic scoring advantage; equivalent outcomes and evidence receive equivalent credit. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |
| 9 | Enterprise Architecture approves every threshold change and explicitly marks 0.1.0-draft provisional; no pilot tuning is adopted informally. | `{{analysis}}` | `{{Pass/Fail/Insufficient evidence}}` | `{{issue/None}}` |

**Overall acceptance status:** `{{All nine passed/One or more failed/Insufficient evidence}}`. A single failed or unresolved criterion keeps the model provisional.

## Methodology and repository-type bias analysis

| Grouping | n | Mean/median residual or score delta | Rating-disagreement rate | N/A rate | Gate-disagreement rate | Interpretation/limitation |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `{{Canonical methodology profile}}` | `{{n}}` | `{{value}}` | `{{%}}` | `{{%}}` | `{{%}}` | `{{analysis}}` |
| `{{Canonical repository type}}` | `{{n}}` | `{{value}}` | `{{%}}` | `{{%}}` | `{{%}}` | `{{analysis}}` |

Document matched-case tests, profile-specific disputes, type-specific N/A inflation checks, and the limits imposed by a 12-repository sample. Do not infer universal statistical neutrality from this cohort.

## Sensitivity tests

| Test | Locked baseline | Alternative(s) | Grade/rank changes | Methodology/type effect | Decision |
| --- | --- | --- | --- | --- | --- |
| Letter-grade boundaries | `{{baseline}}` | ±5 points | `{{result}}` | `{{result}}` | `{{retain/propose study}}` |
| Assurance mappings and thresholds | `{{baseline}}` | `{{alternatives}}` | `{{result}}` | `{{result}}` | `{{decision}}` |
| Unknown treatment | Unknown = 0 | Display-only exclusion for sensitivity only | `{{result}}` | `{{result}}` | `{{decision}}` |
| Dimension weighting | Equal applicable dimensions | `{{reasonable alternatives}}` | `{{result}}` | `{{result}}` | `{{decision}}` |
| Foundational gates | Four gates together | Each gate independently and combinations | `{{result}}` | `{{result}}` | `{{decision}}` |
| N/A-heavy profiles | Current normalization | `{{stress cases}}` | `{{result}}` | `{{result}}` | `{{decision}}` |
| Risk-tier treatment | Baseline/Elevated/Critical rules | Matched facts across tiers | `{{result}}` | `{{result}}` | `{{decision}}` |

## Calibration issues, changes, and limitations

| ID | Type | Evidence/problem | Affected controls/profiles/types | Proposed disposition | Normative impact? | Owner/date | Architecture approval required? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{{CAL-001}}` | `{{Ambiguity/bias/threshold/evidence/access/training}}` | `{{detail}}` | `{{scope}}` | `{{retain/reword/retest/change}}` | `{{Yes/No}}` | `{{owner/date}}` | `{{Yes/No}}` |

State cohort limitations, missing systems, assessor-training effects, sparse strata, unresolved N/A decisions, excluded data, and any reason a criterion could not be evaluated.

## Enterprise Architecture exit decision

| Decision field | Value |
| --- | --- |
| Decision | `{{Continue provisional/Repeat pilot/Approve calibrated successor version}}` |
| Approved standard version/effective date | `{{version/date or N/A}}` |
| Threshold or scoring changes approved | `{{IDs/None}}` |
| Conditions and required follow-up | `{{conditions}}` |
| Decision rationale | `{{rationale linked to all nine criteria}}` |
| Enterprise Architecture approver | `{{name/role}}` |
| Approval date | `{{date}}` |
| Cross-functional review reference | `{{record}}` |
| Dissent or reservations | `{{record/None}}` |

Until this section contains an authorized decision approving a calibrated successor, all pilot scores and conclusions remain provisional and must not be represented as certification, compliance attestation, or enterprise calibration.
