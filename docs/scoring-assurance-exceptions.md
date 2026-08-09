# Scoring, Assurance, and Exceptions

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | **Provisional — pilot calibration required** |
| Accountable owner | Enterprise Architecture |
| Applies to | Assessments performed against Repository Health Standard 0.1.0-draft |

This document defines how an assessment becomes a score, how strongly that score is supported, and how applicability and accepted risk are represented. It must be used with the [Repository Health Standard](repository-health-standard.md), [Classification Guide](classification-guide.md), and [Glossary](glossary.md).

The Repository Health Standard, this scoring guide, and the [Control Catalog](control-catalog.md) are jointly normative within their assigned domains. If their requirements appear to conflict, apply this precedence: the Repository Health Standard governs scope, principles, and required outcomes; this guide governs scoring, assurance, gate-cap, N/A, and exception mechanics; and the Control Catalog governs each control's requirement, applicability, minimum assurance, freshness, threshold, grade effect, and remediation outcome. The [Measurement Dictionary](measurement-dictionary.md) supplies the binding calculation for a measure incorporated by a control but cannot override the preceding documents. Record an unresolved conflict and do not improvise a rating.

The score is a concise summary, not a substitute for the underlying evidence, dimension results, gate results, or findings. Every published result must retain those components.

## 1. Required assessment result

Every assessment reports all of the following:

- repository type, workflow profile, risk tier, and classification confidence;
- raw score and effective/capped score from 0 through 100;
- calculated letter grade and maturity level;
- effective letter grade and maturity level after any gate cap;
- eight dimension results, including any approved `N/A` dimensions;
- assurance index and assurance label;
- each foundational gate result;
- evidence coverage, unknowns, exceptions, and assessment limitations;
- standard version, assessment date, evidence cutoff date, and assessors; and
- a separate DORA outcome panel when product-level delivery data is available.

Do not publish a score or badge without a link or reference to this supporting result.

## 2. Control conformance

Controls receive one conformance state. Numeric points measure conformance; they do not measure evidence strength.

| State | Points | Meaning |
| --- | ---: | --- |
| Met | 100 | The required outcome is satisfied across the assessed scope and the evidence meets the control's minimum assurance requirement. |
| Partially met | 50 | Some of the required outcome is present, its scope is incomplete, or evidence is below the required level but supports more than an unknown result. |
| Unmet | 0 | Evidence shows that the required outcome is absent or ineffective. |
| Unknown | 0 | The assessor cannot determine conformance from acceptable evidence. Unknown is reported separately from Unmet even though both contribute zero points. |
| N/A | Excluded | The control is not applicable under an approved type/profile rationale. N/A is not a passing result. |

`Exemplary` may be added as a non-numeric annotation to a Met control. It never contributes more than 100 points and cannot offset a weakness elsewhere.

Where a control includes multiple required elements, the control definition must say whether all elements are required or how they are combined. Assessors may not invent partial-credit formulas during an assessment.

Unless a control defines a different qualitative decision rule, a measurement result of Pass maps to Met, Concern maps to Partially met, Fail maps to Unmet, and missing or indeterminate data maps to Unknown.

## 3. Evidence assurance

Each control receives the highest evidence level fully supported by the evidence inventory. A higher level incorporates the lower-level expectations where they are relevant.

| Level | Name | What it establishes | Typical evidence |
| --- | --- | --- | --- |
| E0 | Unknown | No acceptable, current evidence establishes the claim. | Missing access, unavailable records, unsupported assertion, or evidence outside the allowed scope/window. |
| E1 | Declared | An accountable source states the intended policy or process. | Versioned policy, repository documentation, owner attestation, or approved workflow declaration. |
| E2 | Configured | A mechanism capable of enforcing or performing the declared behavior is currently configured. | Branch/ruleset settings, workflow definitions, ownership configuration, dependency policy, or release configuration. |
| E3 | Demonstrated | Recent records show the configured behavior operating across the required scope. | CI history, merge records, release records, approvals, deployment records, or exercised recovery evidence. |
| E4 | Sustained effectiveness | Sustained evidence shows the behavior produces the required result across the control's observation window. | Healthy longitudinal build results, complete source-to-artifact lineage, successful recovery exercises, or outcome trend with documented exceptions. |

Evidence level and conformance answer different questions. For example, E3 evidence may demonstrate that a control is Unmet, while an E1 declaration normally cannot support a Met rating for an enforced technical control.

### 3.1 Minimum evidence and freshness

Every control must define its minimum evidence level, evidence source, observation window, and freshness rule for each applicable risk tier. Until the catalog defines a narrower rule, use these provisional defaults:

- inspect current configuration plus the trailing 90 days of relevant events;
- when fewer than five relevant events occurred, extend the lookback to 365 days and label the measure `Low Sample` if fewer than five events remain;
- do not penalize a stable low-activity repository merely because it has fewer events;
- do not infer an outcome from inactivity: configuration may establish E2, while E3 or E4 requires relevant exercised evidence; and
- downgrade stale evidence to the highest level its currentness actually supports and record the limitation.

For a technical enforcement control, E1 caps conformance at Partially met. E2 may support Met only when current configuration is itself the full required outcome. Controls requiring actual execution need E3; controls requiring sustained effectiveness need E4.

### 3.2 Assurance index and label

Assurance is calculated across applicable controls independently of conformance:

| Evidence level | Assurance points |
| --- | ---: |
| E0 | 0 |
| E1 | 25 |
| E2 | 50 |
| E3 | 75 |
| E4 | 100 |

```text
assurance index = sum(assurance points for applicable controls)
                  / count(applicable controls)
```

| Assurance label | Rule |
| --- | --- |
| High | Index is at least 75, and no applicable foundational gate is supported below E3. |
| Moderate | Index is at least 50 but does not satisfy the High rule. |
| Low | Index is below 50. |

N/A controls are excluded. Unknown controls remain applicable and contribute E0. Report the evidence-level distribution beside the index so the average cannot hide important gaps.

## 4. Dimension and overall scoring

The eight dimensions are equally weighted. For a fully applicable assessment, each contributes 12.5 percent:

| Code | Dimension | Weight |
| --- | --- | ---: |
| SPI | Source-to-production integrity | 12.5% |
| BTC | Build, test, and CI health | 12.5% |
| CGD | Change governance and branch discipline | 12.5% |
| SSC | Security and software-supply-chain health | 12.5% |
| OWM | Ownership and maintainability | 12.5% |
| DCR | Documentation and contributor readiness | 12.5% |
| RRO | Release, rollback, and operational readiness | 12.5% |
| RLP | Repository lifecycle and portfolio hygiene | 12.5% |

Within a dimension, each applicable control has equal weight unless a future version of the standard explicitly assigns control weights. Provisional 0.1.0-draft does not permit assessor-selected weights.

```text
dimension score = sum(conformance points for applicable controls in dimension)
                  / count(applicable controls in dimension)

raw score = sum(dimension scores for applicable dimensions)
            / count(applicable dimensions)
```

If every control in a dimension is legitimately N/A, exclude that dimension and re-normalize equally across the remaining applicable dimensions. The report must show the reduced dimension and control coverage; scores with materially different applicability are not assumed to be directly comparable.

Calculate using unrounded values. Display dimension and overall scores to one decimal place in reports, workbooks, and machine-readable exports. Determine grade bands from the unrounded raw score.

### 4.1 Letter grade and maturity

| Raw score | Letter | Maturity | Interpretation |
| ---: | --- | --- | --- |
| 90 to 100 | A | M4 — Leading | The repository consistently satisfies the standard with strong, current controls. |
| 80 to less than 90 | B | M3 — Managed | Core practices are managed; remaining gaps are bounded and visible. |
| 70 to less than 80 | C | M2 — Defined | Important practices exist, but material gaps or inconsistency remain. |
| 60 to less than 70 | D | M1 — Developing | Foundational weaknesses materially reduce confidence in repository health. |
| 0 to less than 60 | F | M0 — At Risk | Required practices are broadly absent, ineffective, or not evidenced. |

The maturity label is another representation of the same numeric result, not a separate calculation.

## 5. Foundational gates and the D cap

The standard defines four foundational gates:

| Gate | Required outcome |
| --- | --- |
| G-01 | Main is buildable, validated, and releasable under the repository type and support contract at the exact assessed revision. |
| G-02 | The production, published, or otherwise released identity is traceable to an immutable revision reachable from Main. |
| G-03 | Changes reaching Main follow a controlled and auditable path appropriate to the declared workflow. |
| G-04 | Production-critical branches, tags, environments, and equivalent references are protected against uncontrolled change. |

Each gate is reported as `Pass`, `Fail`, `Unknown`, or approved `N/A`. Pass requires a Met control result at the risk tier's minimum evidence level; Partially met or Unmet is a gate Fail.

- Any applicable gate rated Fail or Unknown caps the effective result at **69.0 / D / M1**.
- The raw score and calculated grade remain visible. The effective score is `min(raw score, 69.0)` and the effective grade/maturity follows that capped score; a raw F remains F/M0.
- An approved risk exception does not change conformance, erase an unknown, or lift the cap.
- An equivalent control may Pass only when it satisfies the same required outcome and evidence threshold.
- In a monorepo or repository with multiple production units, use the least healthy applicable production unit for each gate. A scope-specific gate failure caps the repository result and must identify the affected unit.
- N/A is permitted only where the repository classification makes the outcome genuinely inapplicable and the rationale is approved. Being difficult to measure is not N/A.
- G-01, G-03, and G-04 normally remain applicable to mirrors, sandboxes, and archives under their type-specific validation, controlled-change, and reference-protection contracts. G-02 is the gate most commonly N/A when there is evidence of no deployed or published output.

## 6. Baseline, Elevated, and Critical risk tiers

The repository classification assigns one risk tier. Risk tiers raise control applicability, evidence, freshness, and approval expectations; they do not alter the eight equal dimension weights.

| Risk tier | Intended use | Provisional assurance expectation |
| --- | --- | --- |
| Baseline | Default for active repositories without elevated business, regulatory, safety, data, or availability exposure. | Current E2 may establish static/configuration controls; execution and outcome controls still require E3/E4 as defined. |
| Elevated | Repositories supporting material business services, sensitive data, customer-facing delivery, or important shared components. | Applicable gates and operational controls normally require E3; technical enforcement is preferred over declaration. |
| Critical | Repositories with safety, regulatory, systemic, privileged, or highest-availability consequences. | Gates require E3 or stronger; provenance and sustained-outcome controls use E4 where specified, with independent or tamper-resistant evidence where feasible. |

The control catalog, not the assessor, determines tier-specific requirements. A repository can earn A under any supported methodology and risk tier when it meets the applicable requirements with adequate evidence.

## 7. N/A, unknowns, and equivalent controls

### 7.1 N/A

An N/A disposition requires:

- repository type and workflow profile;
- the specific control or dimension;
- the factual reason the required outcome is inapplicable;
- evidence supporting that classification;
- approver and approval date; and
- reassessment trigger or next review date.

N/A is excluded from the score and assurance denominator. Mirrors, archives, sandboxes, and non-deployable repositories use type-appropriate applicability; they are not automatically unhealthy because deployable-software controls do not apply.

### 7.2 Unknown

Unknown means the control remains applicable but acceptable evidence is unavailable or insufficient. It contributes zero conformance and E0 assurance points. A gate Unknown triggers the D cap. The report must distinguish whether the gap arises from repository practice, evidence retention, assessment access, or scope ambiguity.

### 7.3 Equivalent controls

Methodologies may meet the same outcome through different mechanisms. An equivalent control is rated normally when its owner documents:

- the original required outcome;
- the alternate mechanism and scope;
- evidence showing equal or stronger prevention, detection, and traceability; and
- Architecture approval when the equivalence is not already recognized in a methodology profile.

Approved equivalence is not an exception and does not reduce the score.

## 8. Exceptions and accepted risk

The assessment decision register supports three disposition types: `N/A determination`, `Equivalent control`, and `Temporary waiver`. Sections 7.1 and 7.3 govern the first two. In this section, **exception** means a Temporary waiver that accepts an unmet requirement for a limited period. It does not convert the underlying control to Met.

### 8.1 Required exception record

| Field | Requirement |
| --- | --- |
| Exception ID | Stable identifier. |
| Decision type | Temporary waiver. |
| Repository and scope | Repository, component, branch, environment, and production unit affected. |
| Standard version and control | Exact requirement being excepted. |
| Risk tier and workflow | Classification at approval time. |
| Condition and evidence | Current conformance, assurance level, and evidence references. |
| Risk statement | Threat or failure, likelihood, impact, and affected parties. |
| Business justification | Why the requirement cannot be met within the normal period. |
| Compensating controls | Current measures that reduce likelihood or impact. |
| Remediation plan | Outcome, accountable owner, milestones, and target completion. |
| Risk acceptor | Named role with authority for the affected risk. |
| Architecture disposition | Review outcome and any conditions. |
| Dates | Requested, approved, effective, next review, and expiration. |
| Status and history | Proposed, Active, Expired, Revoked, or Closed, plus approval and renewal history. |

### 8.2 Duration and renewal

- Temporary waivers default to **90 calendar days**.
- Baseline exceptions may be approved for up to **180 calendar days** when the risk and remediation plan justify the longer period.
- Elevated and Critical exceptions may run for at most **90 calendar days**.
- Shorter periods are required when the remediation plan or risk warrants them.
- Exceptions expire automatically; there is no evergreen or implicit renewal.
- Renewal requires updated evidence, residual-risk review, progress against milestones, a new expiration within the same 90/180-day maximum, and fresh approval.
- An expired exception remains visible as an overdue accepted-risk item and provides no special assessment treatment.

### 8.3 Score treatment

The control retains its observed Unmet, Partially met, or Unknown state. The assessment shows the exception alongside the finding and may distinguish accepted from unaccepted risk in reporting. Gate caps remain in force. Exception count, age, and days to expiration are reported separately and are not bonus or penalty points.

## 9. Separate DORA outcome panel

When reliable product-level delivery data is available, report these five outcome measures separately:

- change lead time;
- deployment frequency;
- failed deployment recovery time;
- change fail rate; and
- deployment rework rate.

For each measure, identify the application/service, source, formula, observation window, coverage, and limitations. Every report, workbook, or exchange artifact must mark the panel `informative_only: true`. Do not add DORA values to the 0–100 repository-health score, use them as foundational gates, or compare unrelated products as though their operating contexts were equivalent. Use the panel to test whether repository practices and delivery outcomes tell a coherent story over time.

## 10. Provisional status

All weights, bands, assurance mappings, evidence defaults, and gate behavior in this document are provisional 0.1.0-draft. Changes require the governance and pilot process in [Governance and Pilot](governance-and-pilot.md). Every assessment must preserve its original standard version so later calibration does not silently rewrite historical results.
