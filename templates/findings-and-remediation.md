# Findings and Remediation Register

> Template version 0.1.0-draft — provisional. Findings state evidenced conditions and outcomes. Remediation closes the required outcome; activity alone does not close a finding.

## Register identity

| Field | Value |
| --- | --- |
| Assessment ID | `{{ID}}` |
| Repository | `{{owner/repository}}` |
| Standard version | `0.1.0-draft` |
| Repository owner | `{{name/role}}` |
| Register updated | `{{date}}` |

## Priority definitions

| Priority | Use |
| --- | --- |
| P0 — Foundational | Failed/Unknown gate or immediate condition with material production/release integrity consequence. |
| P1 — High | Material applicable-control gap requiring near-term risk reduction. |
| P2 — Planned | Bounded weakness that should be addressed through normal planning. |
| P3 — Improvement | Low-risk improvement or exemplary-practice opportunity. |

Priority does not alter the numeric score. Gate behavior follows the scoring standard.

## Findings register

| Finding | Status | Priority | Dimension | Control/gate | Scope | Conformance | Assurance | Evidence | Condition and risk | Owner | Target | Exception |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `{{F-001}}` | `{{Open/etc.}}` | `{{P0–P3}}` | `{{code}}` | `{{ID}}` | `{{unit/ref/env}}` | `{{Partially met/Unmet/Unknown}}` | `{{E0–E4}}` | `{{EV IDs}}` | `{{concise summary}}` | `{{role}}` | `{{date}}` | `{{EX ID/None}}` |

## Individual finding

### `{{F-001 — Outcome-focused title}}`

| Field | Detail |
| --- | --- |
| Standard/control | `{{version and ID}}` |
| Dimension and gate | `{{dimension; gate ID/None}}` |
| Affected scope | `{{repository/component/branch/environment/production unit}}` |
| Observed condition | `{{specific, neutral fact}}` |
| Required outcome | `{{standard outcome}}` |
| Conformance/assurance | `{{state; E-level; freshness}}` |
| Evidence | `{{EV IDs and dates}}` |
| Risk/consequence | `{{credible failure or stakeholder effect}}` |
| Existing safeguards | `{{current controls/None}}` |
| Root cause | `{{known hypothesis/Not established}}` |
| Priority rationale | `{{why P0–P3}}` |
| Exception | `{{ID/status/None}}` |

**Remediation acceptance criteria**

- `{{Observable required outcome.}}`
- `{{Minimum evidence level, scope, and observation window.}}`
- `{{Test or review that establishes closure without introducing a new gate failure.}}`

## Remediation plan

| Finding | Outcome/milestone | Accountable owner | Target date | Dependency | Completion evidence required | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `{{F-001}}` | `{{outcome}}` | `{{role}}` | `{{date}}` | `{{dependency/None}}` | `{{evidence}}` | `{{Not started/In progress/Blocked/Complete}}` |

Plans may include implementation tasks, but assessment closure is based on the acceptance criteria and fresh evidence, not task completion alone.

## Exceptions and accepted risk

| Exception | Type | Finding/control | Risk tier | Risk acceptor | Compensating controls | Approved | Review | Expires | Remediation owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `{{EX-001}}` | `{{Temporary waiver}}` | `{{F/Control IDs}}` | `{{Baseline/Elevated/Critical}}` | `{{role}}` | `{{summary}}` | `{{date}}` | `{{date}}` | `{{<=180 or <=90 days}}` | `{{role}}` | `{{status}}` |

The underlying rating and any gate cap remain unchanged while an exception is approved.

## Closure verification

| Finding | Claimed complete | Verification evidence | Reassessed conformance | Reassessed assurance | Gate/score effect | Verified by/date | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{{F-001}}` | `{{date}}` | `{{EV IDs}}` | `{{state}}` | `{{E-level}}` | `{{effect}}` | `{{assessor/date}}` | `{{Closed/Reopened/Monitor}}` |

## Portfolio summary

| Measure | Value |
| --- | ---: |
| Open P0/P1/P2/P3 | `{{n/n/n/n}}` |
| Open gate findings | `{{n}}` |
| Unknown findings | `{{n}}` |
| Approved exceptions | `{{n}}` |
| Exceptions expiring within 30 days | `{{n}}` |
| Expired exceptions | `{{n}}` |
| Findings closed with verified evidence | `{{n}}` |
