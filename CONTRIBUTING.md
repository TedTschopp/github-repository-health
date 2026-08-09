# Contributing to the Standard

## Decision rights

Enterprise Architecture is accountable for the normative standard, control catalog, scoring policy, profile approval, and version history. Engineering, platform engineering, security, operations/SRE, compliance, and repository maintainers are required reviewers for changes affecting their domains.

## Change classes

| Change | Version effect | Approval |
| --- | --- | --- |
| Typographical correction with no semantic effect | Patch | Document owner |
| Clarification that does not change applicability, evidence, or scoring | Patch | Enterprise Architecture |
| New or changed control, metric, profile, threshold, gate, or risk-tier requirement | Minor during 0.x; major after 1.0 when incompatible | Enterprise Architecture plus affected domain reviewers |
| Removal or incompatible redefinition of a normative requirement | Major | Enterprise Architecture and governance approval under enterprise policy |

## Required change record

A proposed normative change must state:

1. The affected control, metric, profile, or policy identifiers.
2. The problem and supporting evidence.
3. The proposed wording and expected scoring impact.
4. Repository types, methodologies, and risk tiers affected.
5. Backward-compatibility and migration implications.
6. External-source changes, if any.
7. Pilot or regression cases used to validate the change.
8. Required reviewers and final decision.

## Review rules

- Preserve outcome-based requirements. Do not make a hosting platform, branching fashion, tool, or vendor mandatory when equivalent evidence can satisfy the outcome.
- Do not weaken a foundational gate through weighting or compensation.
- Add or update a measurement definition whenever normative wording changes what an assessor must observe.
- Re-run the worked-example and pilot regression cases for scoring changes.
- Record accepted changes in `CHANGELOG.md` and update the standard version on every affected artifact.
- Publish rejected proposals and their rationale in the decision record used by Enterprise Architecture.

## Automation changes

The assessment engine, report renderer, composite action, and example workflows are supporting implementations of the controlled documents. A change to supporting automation must not silently change applicability, a threshold, a gate, scoring, assurance, exception treatment, or methodology classification.

An automation change must:

1. Name the control, measure, schema, or reporting contract it implements.
2. Preserve missing or inaccessible evidence as `Unknown`; it must never infer a pass from an API error or absent record.
3. Keep DORA outcomes outside the repository-control score.
4. Remain read-only unless a separately approved future change explicitly introduces another operating mode.
5. Add regression coverage for the affected evidence, scoring, or report behavior.
6. Run `python3 -m unittest discover -s tests -v` and record any environment-dependent validation that could not be completed.
7. Update the [Automated Assessment Guide](docs/automation-guide.md), artifact schema, examples, and changelog when a public input or output changes.

The provisional workflow must not fail because a repository has a low score, failed gate, or low assurance. Execution, invalid configuration, catalog incompatibility, and incomplete report generation may fail the workflow so that a missing assessment is visible.

## External-source refresh

When a pinned reference changes, first document the delta and its relevance. A newer source version does not silently alter this standard. Enterprise Architecture must explicitly adopt, adapt, or decline the change.
