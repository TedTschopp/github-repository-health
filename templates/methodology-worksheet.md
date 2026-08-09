# Repository Type and Methodology Worksheet

> Template version 0.1.0-draft — provisional. Classify before scoring. Record both declared intent and observed practice; do not force a hybrid repository into a familiar label or use Custom/hybrid to conceal insufficient evidence.

## Repository and assessment

| Field | Value |
| --- | --- |
| Repository | `{{owner/repository}}` |
| Assessment ID/date | `{{ID/date}}` |
| Assessor | `{{name/role}}` |
| Evidence cutoff | `{{timestamp}}` |
| Main/canonical integration line | `{{ref}}` |
| Accountable owner | `{{role/team/Unknown}}` |

## 1. Repository type

Select one primary type and any secondary types. Cite evidence for lifecycle and production status.

- [ ] Deployable application
- [ ] Library/package
- [ ] Monorepo
- [ ] Infrastructure-as-code/GitOps
- [ ] Data/analytics/model
- [ ] Documentation/content
- [ ] Template/scaffold
- [ ] Sandbox/experimental
- [ ] Mirror/fork
- [ ] Archived/retired

| Decision | Value |
| --- | --- |
| Primary type | `{{type}}` |
| Secondary type(s) | `{{types/None}}` |
| Lifecycle state | `{{Active/Stable-supported/Experimental/Mirrored/Archived/Retired/Unknown}}` |
| Deployable or publishable units | `{{list/None}}` |
| Evidence | `{{IDs}}` |
| Classification confidence | `{{High/Moderate/Low}}` |
| Ambiguity to resolve | `{{issue/None}}` |

## 2. Production and release truth

| Question | Answer | Evidence |
| --- | --- | --- |
| What does “production,” “published,” or “released” mean for this repository? | `{{definition/Not applicable}}` | `{{IDs}}` |
| What immutable identity names the current production/published state? | `{{SHA/tag/digest/version/state ID/Unknown/N/A}}` | `{{IDs}}` |
| How is that identity traced to Main? | `{{path/Unknown/N/A}}` | `{{IDs}}` |
| Can Main be ahead of production? Under what bounded promotion rule? | `{{rule}}` | `{{IDs}}` |
| Are there multiple independently released units? | `{{units/No}}` | `{{IDs}}` |
| What references or environments can change production? | `{{list}}` | `{{IDs}}` |

## 3. Workflow axes

| Axis | Declared behavior | Observed behavior | Evidence | Match? |
| --- | --- | --- | --- | --- |
| Canonical integration topology | `{{one Main/Main plus develop/environment lines/supported version lines/hierarchical integrators}}` | `{{observed}}` | `{{IDs}}` | `{{Yes/No/Partially aligned}}` |
| Change ingress | `{{direct push/gated direct/branch review/fork review/bot or integration-manager}}` | `{{observed}}` | `{{IDs}}` | `{{...}}` |
| Branch purpose and lifetime | `{{no routine branches/short-lived topic/release/environment/maintenance}}` | `{{observed distribution and cadence}}` | `{{IDs}}` | `{{...}}` |
| Integration cadence | `{{continuous/batch or train/release-driven/irregular}}` | `{{observed}}` | `{{IDs}}` | `{{...}}` |
| Release source | `{{Main revision or tag/release branch/environment branch/generated artifact/GitOps ref or path}}` | `{{observed}}` | `{{IDs}}` | `{{...}}` |
| Promotion mechanism | `{{promote immutable artifact/rebuild/merge/cherry-pick or backport/desired-state change/reconciliation}}` | `{{observed}}` | `{{IDs}}` | `{{...}}` |
| Parallel support | `{{current only/temporary stabilization/multiple supported versions/multiple trains}}` | `{{observed}}` | `{{IDs}}` | `{{...}}` |
| Control placement | `{{pre-submit/pre-merge/post-merge/pre-release/environment approval/reconciler admission}}` | `{{observed}}` | `{{IDs}}` | `{{...}}` |
| Repository topology | `{{shared canonical/contributor forks/downstream fork/mirror/coordinated repositories}}` | `{{observed}}` | `{{IDs}}` | `{{...}}` |

## 4. Workflow profile decision

Choose the closest supported profile, then document deviations. A profile changes acceptable implementation evidence, not the required health outcome.

- [ ] Trunk-based
- [ ] GitHub Flow/short-lived feature branches
- [ ] GitFlow
- [ ] Environment-branch flow
- [ ] Release train/multi-version maintenance
- [ ] GitOps promotion
- [ ] Fork/integration-manager
- [ ] Direct gated trunk
- [ ] Custom/hybrid
- [ ] Unclassified — insufficient evidence; Low confidence required

| Decision | Value |
| --- | --- |
| Declared profile | `{{canonical profile/Unknown}}` |
| Observed profile | `{{canonical profile/Unclassified}}` |
| Final assessment profile | `{{canonical profile/Unclassified}}` |
| Material deviations/hybrid facets | `{{description}}` |
| Declared-versus-observed finding needed? | `{{Yes/No; finding ID}}` |
| Evidence | `{{IDs}}` |
| Confidence | `{{High/Moderate/Low}}` |

## 5. Risk tier

| Factor | Baseline | Elevated | Critical | Evidence/notes |
| --- | --- | --- | --- | --- |
| Business/service impact | `{{mark}}` | `{{mark}}` | `{{mark}}` | `{{notes}}` |
| Safety/regulatory exposure | `{{mark}}` | `{{mark}}` | `{{mark}}` | `{{notes}}` |
| Data sensitivity/privilege | `{{mark}}` | `{{mark}}` | `{{mark}}` | `{{notes}}` |
| Shared dependency/systemic reach | `{{mark}}` | `{{mark}}` | `{{mark}}` | `{{notes}}` |
| Availability/recovery consequence | `{{mark}}` | `{{mark}}` | `{{mark}}` | `{{notes}}` |

**Assigned tier:** `{{Baseline/Elevated/Critical}}`
**Rationale and approver:** `{{rationale; role/date}}`

## 6. Applicability decisions

| Control/dimension | Proposed disposition | Type/profile rationale | Evidence | Approval needed? | Reassessment trigger |
| --- | --- | --- | --- | --- | --- |
| `{{ID}}` | `{{Applicable/N/A/Equivalent}}` | `{{reason}}` | `{{IDs}}` | `{{role/No}}` | `{{date/event}}` |

Special checks:

- [ ] A mirror is assessed for authorized synchronization, provenance, ownership, and lifecycle rather than local feature delivery.
- [ ] An archive is assessed for explicit retired state, ownership, immutability/access, retention, and successor guidance.
- [ ] A sandbox is explicitly non-production; any route to production is either removed or assessed.
- [ ] A stable low-activity repository uses the control-defined last-event window and is not downgraded for low activity alone.
- [ ] A monorepo lists every independently released unit and uses the least healthy applicable unit for each gate.

## 7. Classification sign-off

| Role | Name | Decision | Date | Notes |
| --- | --- | --- | --- | --- |
| Assessor | `{{name}}` | `{{Complete}}` | `{{date}}` | `{{notes}}` |
| Repository owner | `{{name}}` | `{{Facts confirmed/disputed}}` | `{{date}}` | `{{notes}}` |
| Architecture/applicability approver | `{{name/N/A}}` | `{{Approved/Pending/N/A}}` | `{{date}}` | `{{decision IDs}}` |
