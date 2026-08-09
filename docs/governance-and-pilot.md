# Governance and Pilot Calibration

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | **Provisional — not yet calibrated for production use** |
| Accountable owner | Enterprise Architecture |
| Review model | Cross-functional |

This document governs change, review, appeal, and pilot calibration for provisional 0.1.0-draft; it is not a plan to build an automated assessment product. Assessment outcomes are governed by the [normative assessment set and precedence](repository-health-standard.md#normative-document-set-and-precedence).

## 1. Decision rights

Enterprise Architecture owns the standard and is accountable for its coherence across repository types, workflows, and organizational risk tiers. Cross-functional review is required because no single discipline can validate build, security, operations, governance, and contributor-readiness expectations alone.

| Role | Responsibilities and authority |
| --- | --- |
| Enterprise Architecture | Owns the standard; approves dimensions, foundational gates, thresholds, grade bands, risk-tier policy, recognized equivalences, and publication of a new version. Only Enterprise Architecture may approve a scoring-threshold change. |
| Standards steward | Maintains source documents, issue and decision logs, version history, control metadata, templates, and scheduled reviews. May publish non-normative corrections that do not change assessment outcomes. |
| Cross-functional review group | Provides representatives from application engineering, platform/DevEx, quality engineering, security, operations/SRE, release management, and risk/compliance as applicable. Reviews proposed normative changes, pilot results, methodology neutrality, and disputed interpretations. |
| Control-domain owner | Maintains the rationale, evidence expectations, freshness, and thresholds for controls in an assigned domain; cannot unilaterally change scoring. |
| Assessment lead | Defines assessment scope, protects assessor independence, confirms evidence cutoff, validates calculations, and publishes limitations. |
| Assessor | Classifies, collects and cites evidence, rates controls and gates, records unknowns/N/A, and signs the unadjudicated result. |
| Repository owner | Confirms factual scope and evidence access, responds to findings, and owns remediation; does not self-approve disputed ratings. |
| Risk acceptor | Accepts time-bounded residual risk within delegated authority. Acceptance does not change the health score or lift a gate cap. |
| Adjudication chair | Facilitates disagreements and records precedent. Enterprise Architecture decides disputes that would create or change policy. |

The same person may fill more than one operational role in a small organization, but the assessor and risk acceptor should be independent for Elevated and Critical repositories.

## 2. Version and change policy

Every control, template, assessment, exception, and worked example must identify the standard version it uses.

| Change class | Examples | Version treatment | Approval |
| --- | --- | --- | --- |
| Normative major | Add/remove a dimension or gate; change scoring model; materially change applicability. | New major version; migration and re-baseline required. | Enterprise Architecture after cross-functional review. |
| Normative minor | Add a control/profile; change threshold, grade band, risk-tier requirement, or accepted equivalence. | New minor version; impact analysis and effective date required. | Enterprise Architecture after cross-functional review. |
| Editorial patch | Correct wording, links, examples, or template guidance without changing an assessment result. | Patch version. | Standards steward, with change log. |

No normative change is retroactive. Historical assessments retain their original result and version; a re-assessment produces a new record.

### 2.1 Normative change flow

1. Log the proposal, problem statement, affected controls/profiles, and sponsor.
2. Provide evidence, alternatives, expected scoring impact, and transition needs.
3. Test the proposal against representative repository types and every supported methodology it might affect.
4. Run scoring and methodology-bias sensitivity checks.
5. Obtain cross-functional review and record dissent or conditions.
6. Obtain Enterprise Architecture approval for any normative or threshold change.
7. Publish the decision, rationale, effective date, migration guidance, and change log.

Emergency interpretation notices may clarify an immediate ambiguity but cannot change a threshold or silently alter a score. Convert any normative emergency decision into the normal change flow.

### 2.2 Review cadence

- During provisional 0.1.0-draft, review issues at least monthly through pilot completion.
- After calibration, review operational feedback quarterly and conduct a full calibration review annually.
- Review external reference changes when they materially affect a control; adoption is a governed decision, not automatic inheritance.
- Revisit expired equivalences and repeated exception patterns during each calibration review.

## 3. Assessment review, appeal, and precedent

Repository owners may challenge facts, applicability, evidence interpretation, or arithmetic. An appeal must identify the disputed item and provide evidence; disagreement with an unfavorable result alone is insufficient.

1. The assessment lead corrects factual or arithmetic errors and preserves the original record.
2. The two assessors reconsider the cited control using the same standard version and evidence cutoff.
3. Unresolved interpretation disputes go to the adjudication chair and relevant control-domain owner.
4. A decision that creates a new equivalence, changes a threshold, or affects multiple profiles goes to Enterprise Architecture.
5. The final report preserves original ratings, adjudicated ratings, rationale, decision date, and precedent identifier.

Precedents are published internally in a reusable, non-sensitive form. They expire when the governing standard changes unless the new version explicitly carries them forward.

## 4. Provisional 0.1.0-draft field pilot

The field pilot uses **12 real repositories assessed independently by two assessors each**. The fictional cases in [Worked Assessments](../examples/worked-assessments.md) are a desk-calibration corpus only; they do not replace the field pilot.

### 4.1 Sampling matrix

Select repositories that collectively fill these 12 strata. When a perfect match is unavailable, document the substitution and preserve coverage of all repository classes, workflows, and edge conditions.

| Slot | Repository type | Workflow profile | Risk tier/condition to include |
| ---: | --- | --- | --- |
| 1 | Deployable application | Trunk-based | Critical or Elevated; mature continuous integration/delivery candidate. |
| 2 | Deployable application | GitHub Flow/short-lived feature branches | Elevated; include production-identity evidence. |
| 3 | Deployable application | GitFlow | Elevated; release and hotfix paths exercised. |
| 4 | Deployable application | Environment-branch flow | Critical; production-critical reference controls visible. |
| 5 | Library/package | Release train/multi-version maintenance | Baseline; deliberately stable and low activity. |
| 6 | Infrastructure-as-code/GitOps | GitOps promotion | Critical; desired-state and reconciled-state evidence available. |
| 7 | Library/package | Fork/integration-manager | Baseline; distributed contribution path. |
| 8 | Data/analytics/model | Direct gated trunk | Elevated; reproducibility and published-asset identity in scope. |
| 9 | Monorepo | Custom/hybrid | Critical; multiple independently released production units. |
| 10 | Mirror/fork (Documentation/content facet) | Custom/hybrid | Baseline; upstream-sync and read-only axes; type-appropriate non-deployable applicability. |
| 11 | Archived/retired (former Library/package) | Unclassified (historical: GitFlow) | Baseline archive obligations only; current workflow evidence is intentionally absent. |
| 12 | Template/scaffold or Sandbox/experimental | Custom/hybrid | Baseline; explicit non-production lifecycle declaration. |

The sample must include at least three repositories believed by independent portfolio evidence to be strong and at least three with known problems. The pilot lead MUST hold those expectations in a separate access-restricted allocation record; assessor-facing sample records MUST NOT contain or reveal them before both independent ratings are locked. The remaining repositories should span ordinary, uncertain, and mixed conditions.

### 4.2 Pilot protocol

1. **Pre-register:** Freeze provisional 0.1.0-draft, the 12-repository sample, evidence cutoff, assessors, expected evidence access, and analysis method.
2. **Orient:** Train assessors on definitions and one practice case without disclosing field-repository expectations.
3. **Classify independently:** Each assessor completes the methodology worksheet and applicability decisions before scoring.
4. **Assess independently:** Both assessors use the same evidence cutoff but do not share ratings, notes, or interpretations until submission is locked.
5. **Calculate:** Produce raw dimension scores, raw/effective grade, assurance, gate results, unknown/N/A coverage, and a separate DORA panel where possible.
6. **Compare:** Measure control-rating agreement, score difference, gate detection, classification agreement, and evidence-selection differences.
7. **Adjudicate:** Resolve disagreements without overwriting either original assessment.
8. **Calibrate and test sensitivity:** Evaluate thresholds, evidence mappings, grade bands, gate behavior, applicability, and methodology neutrality.
9. **Review:** The cross-functional group reviews the pilot record, unresolved issues, and proposed changes.
10. **Decide:** Enterprise Architecture approves threshold changes and either retains provisional status, authorizes another pilot round, or approves a calibrated successor version.

### 4.3 Exact acceptance criteria

Provisional 0.1.0-draft passes pilot review only when all of these criteria are satisfied:

1. **Every supported methodology can achieve A when practiced well.** Use field evidence or a matched reference case to demonstrate attainability; the pilot does not require every sampled repository to earn A.
2. **An unbuildable Main, unknown production identity, or uncontrolled production reference always triggers the grade cap.** Every applicable foundational gate failure or unknown must be visible.
3. **Reviewers agree on at least 85 percent of control ratings, the median absolute overall-score difference is no more than 5 points, and both reviewers identify 100 percent of foundational gate failures.**
4. **Every control specifies applicability, evidence, freshness, threshold, unknown handling, and exception handling.** No assessor-created rule may fill a missing field.
5. **Stable low-activity repositories are not penalized merely for activity level.** Results may reflect stale controls or failed outcomes, but not an arbitrary commit or release quota.
6. **Mirrors, archives, sandboxes, and non-deployable repositories receive type-appropriate assessments.** Legitimately inapplicable deployable-software controls are not scored as failures.
7. **Raw evidence and dimension results remain visible beneath the aggregate.** A reader can reproduce the score, assurance, gate cap, and N/A treatment.
8. **No methodology receives a systematic scoring advantage.** Equivalent outcomes and evidence receive equivalent credit across workflows.
9. **Enterprise Architecture approves every threshold change and explicitly marks 0.1.0-draft provisional.** No pilot tuning is adopted informally.

Failure of any criterion keeps the model provisional and creates a tracked calibration issue.

## 5. Calibration and sensitivity analysis

### 5.1 Inter-rater analysis

For each repository and in aggregate, calculate:

- exact agreement across control conformance states;
- agreement on N/A versus applicable and on repository/workflow classification;
- absolute difference in each dimension and overall raw score;
- agreement on gate Pass/Fail/Unknown/N/A; and
- evidence-level disagreement, especially E0 versus E1/E2 and E2 versus E3.

Report the numerator and denominator behind the 85 percent criterion. Controls excluded by both assessors as N/A do not count as rating agreement; disagreement about N/A does count as disagreement. Report the median absolute score difference across the 12 paired assessments.

### 5.2 Threshold and model sensitivity

Recalculate the locked assessments under controlled alternatives without adopting them:

- shift each letter-grade boundary by plus and minus 5 points;
- vary assurance point mappings and High/Moderate boundaries;
- compare conservative Unknown-as-zero treatment with a display-only exclusion to expose its effect, while retaining the 0.1.0-draft rule;
- simulate reasonable dimension-weight alternatives solely to test whether equal weighting hides a dominant risk;
- test each foundational gate independently and together;
- test N/A-heavy profiles for misleadingly inflated results; and
- compare Baseline, Elevated, and Critical risk-tier treatment on matched facts.

Record grade changes, rank changes, methodology effects, and repositories whose result is overly sensitive to one judgment. A sensitivity result informs a governed revision; it never edits a locked field assessment.

### 5.3 Methodology-neutrality tests

- Use matched fictional or real scenarios where different workflows deliver the same outcome and evidence strength.
- Swap only the methodology implementation and confirm the score does not materially change.
- Compare rating residuals and recurring interpretation disputes by profile.
- Review whether activity-based measures disadvantage stable release trains, libraries, or archives.
- Confirm that a team cannot select a less demanding workflow label to avoid the required outcome.

Because 12 repositories are too few for a universal statistical claim, combine the quantitative review with cross-functional adjudication and explicitly retain uncertainty.

## 6. Adjudication and calibration record

For every disagreement, record:

- repository, control/gate, and original ratings;
- evidence used by each assessor;
- disagreement type: fact, classification, applicability, conformance, assurance, threshold, or arithmetic;
- adjudicated result and rationale;
- whether wording, training, control metadata, or scoring needs revision;
- precedent identifier and affected profiles; and
- approver and date.

Do not tune a threshold merely to produce a preferred grade for a sampled repository. A proposed change must state the general principle, show results across all 12 repositories and matched methodology cases, and receive Enterprise Architecture approval.

## 7. Pilot outputs and exit decision

Summarize the completed analysis and exit decision with the blank [Field Pilot Report Template](../pilot/pilot-report-template.md). The pilot produces:

- 24 locked independent assessments plus 12 adjudicated reports;
- coverage and classification matrix;
- inter-rater and gate-detection analysis;
- scoring, assurance, and methodology-neutrality sensitivity report;
- ambiguity, N/A, exception, and evidence-access registers;
- adjudication and precedent log;
- proposed 0.1.0-draft revisions with impact analysis; and
- Enterprise Architecture decision: continue provisional, repeat pilot, or approve a calibrated next version.

Pilot scores are clearly labeled provisional. They must not be used for compensation, punitive ranking, or compliance attestation.
