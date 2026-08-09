# Controlled Trial-Use Guide

**Standard version:** 0.1.0-draft

**Owner:** Enterprise Architecture

## Permitted use

Version 0.1.0-draft may be used for voluntary team diagnostics, assessor training, methodology-neutrality testing, portfolio discovery, and the formal calibration pilot. Results should guide conversations and improvement backlogs.

The provided automation may collect read-only evidence and generate draft assessment and leadership reports for these permitted uses. An automated result remains provisional, must disclose its evidence limitations, and requires human review before it is represented as an issued assessment.

## Prohibited use

Until Enterprise Architecture completes and approves field calibration, a 0.1.0-draft result must not be used as the sole basis to:

- Block a release or deployment.
- Approve or deny funding.
- Rank individual engineers or teams.
- Certify regulatory compliance.
- Publish a repository grade outside the approved pilot audience.
- Claim that an automated control exists or is effective.
- Treat a workflow's successful execution as proof that every assessed control passed.

## Required disclosure

Every trial assessment must say:

> This assessment uses the provisional Git Repository Health Standard 0.1.0-draft. Thresholds have not completed enterprise field calibration. The result is an improvement diagnostic, not a compliance certification or release gate.

## Known limitations

- Thresholds and weights have only provisional status until the 12-repository pilot is complete.
- Manual evidence collection can be slow and access-dependent.
- Some connected systems may not retain enough history for E4 assurance.
- Platform settings show configured controls, not necessarily demonstrated effectiveness.
- Repository boundaries may not align with application, service, product, or deployment boundaries.
- DORA measures are meaningful at an application or service level and can mislead when aggregated across unlike contexts.
- Security controls in this standard are a repository-health baseline, not a complete security assessment or compliance framework.
- A score is sensitive to applicability and evidence quality; raw control results must remain available.
- GitHub-only collection cannot normally establish complete production, operational, security, identity, or portfolio evidence.
- A repository-supplied control override is an evidence reference, not independent verification by the automation.

## Appeals and corrections

1. The repository owner submits the disputed control IDs, evidence, requested disposition, and rationale.
2. The original assessor reviews factual corrections and records any changed result.
3. Unresolved interpretation, equivalent-control, or methodology-profile questions go to Enterprise Architecture.
4. Security or compliance interpretations require the affected domain reviewer.
5. Enterprise Architecture records the decision and determines whether it applies only to the assessment or establishes reusable precedent.
6. A scoring-policy change is versioned; it is never applied silently.

## Trial completion

Enterprise Architecture may advance 0.1.0-draft to controlled-trial status only after the acceptance tests in [Governance and Pilot](governance-and-pilot.md) pass or each deviation is explicitly accepted with rationale. A later v1.0 requires a separate adoption decision.
