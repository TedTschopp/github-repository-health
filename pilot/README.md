# Field Pilot Package

This folder is reserved for the real 12-repository, two-assessor calibration pilot defined in [Governance and Pilot](../docs/governance-and-pilot.md).

The repository currently contains the standards, manual assessment package, and fictional desk-test cases. It does **not** contain completed field-pilot evidence. Do not describe 0.1.0-draft as enterprise-calibrated until Enterprise Architecture approves a completed pilot report.

## Required pilot records

For each selected repository, retain:

- Approved sample-register entry and repository owner's consent.
- Two independently completed assessment workbooks.
- Assessor comparison and adjudication record.
- Redacted evidence index; sensitive evidence remains in its system of record.
- Repository-owner fact check.
- Final accepted assessment used only for calibration.

At pilot level, retain:

- Sample coverage and selection rationale.
- Control-level agreement, score deltas, and gate agreement.
- Methodology and repository-type bias analysis.
- Weight, threshold, and grade-cap sensitivity analysis.
- Ambiguity and gaming register.
- Architecture decisions and the final 0.1.0-draft status.

Use the blank [Field Pilot Report Template](pilot-report-template.md) to report cohort coverage, exact acceptance criteria, agreement and gate-detection calculations, bias and sensitivity analysis, limitations, and the Enterprise Architecture exit decision.

Use `sample-register.csv` to nominate the cohort. Populate real names and assessors only in the authorized pilot workspace.

Use the canonical repository-type and methodology labels from the [Classification Guide](../docs/classification-guide.md). Record an absent declaration as `Unknown` and an unresolved observed profile as `Unclassified` with Low confidence; use `Custom/hybrid` only when the mixed or custom behavior is understood.

The assessor-facing register is intentionally blind to any prior health expectation. The pilot lead must keep strong/known-problem selection strata in a separate access-restricted allocation record and reveal them only after both assessors have locked their independent submissions.
