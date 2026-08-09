# Security Policy

## Supported versions

This project is a provisional standard and assessment implementation. Security
fixes are made on the default branch and included in the next published
release.

| Version | Supported |
| --- | --- |
| `main` and the latest `0.1.x` release | Yes |
| Earlier revisions and superseded releases | No |

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/TedTschopp/github-repository-health/security/advisories/new) for a suspected vulnerability. Do not open a public issue for security-sensitive details.

Include the affected revision or release, affected files or workflow, realistic
impact, reproduction steps, and any suggested remediation. Remove credentials,
tokens, personal data, and unnecessary exploit detail. The maintainer targets
an acknowledgement within five business days and a status update within ten
business days; these targets are not a disclosure deadline or service-level
guarantee.

Use [SUPPORT.md](SUPPORT.md) and public Issues for ordinary defects, usage
questions, and improvements that do not expose a security weakness.

## System and scope

This policy covers the entire repository:

- the normative repository-health standard, control catalog, measures, and
  assessment guidance;
- the standard-library Python evidence collector, evaluator, and report
  renderer under `automation/repository_health/`;
- the local composite action and GitHub Actions workflows under `.github/`;
- generated assessment and leadership-report contracts; and
- examples, templates, pilot material, and the manual workbook when a defect
  could lead users to trust a materially unsafe result.

The project is not an internet-facing service. Its security-sensitive behavior
occurs when GitHub Actions or a local assessor reads repository and GitHub API
data, handles a token, calculates a result, and publishes reports or release
artifacts. Those results can influence governance decisions, so integrity and
evidence provenance are security-relevant.

## Threat model and trust boundaries

Repository content, Git history, branch and tag names, GitHub API responses,
assessment configuration, evidence references, and imported assessment JSON
are untrusted inputs. A workflow token, runner environment, release identity,
and generated report cross trust boundaries. Downstream users may consume the
action from another repository, so a source-repository input must not obtain
code execution merely because it is being assessed.

GitHub and the runner platform are trusted to enforce their documented token,
ruleset, and workflow boundaries. A declaration or test demonstrates intent; it
does not by itself prove sustained effectiveness.

## Security invariants

The following properties must hold:

1. Assessment remains read-only. It must not execute arbitrary code from the
   repository being assessed or mutate that repository.
2. Tokens, credentials, raw secret findings, and sensitive alert details must
   not appear in logs, JSON, Markdown, artifacts, or error messages.
3. Missing, stale, incomplete, contradictory, unauthorized, or inaccessible
   evidence must fail closed to `Unknown`; it must never become a pass.
4. Control ratings, gate status, assurance, exceptions, and DORA outcomes must
   remain traceable and must not be silently promoted or averaged away.
5. Untrusted text must be safely encoded before it is placed in Markdown, HTML,
   shell commands, file paths, URLs, or GitHub workflow outputs.
6. File and API access must remain within the declared repository, configured
   GitHub API origin, and explicit output locations. Redirects and pagination
   must not leak authorization to another origin.
7. Reusable third-party actions must be pinned to reviewed immutable revisions,
   and workflows must use the least permissions needed for their job.
8. A release artifact and its attestation must identify the exact source
   revision and digest; a mutable name alone is not production identity.
9. Configuration, catalog, schema, or evidence-version mismatches must stop the
   assessment rather than silently changing its meaning.

## Reportable findings and severity context

Report a finding when realistic attacker-controlled input can cause token or
secret disclosure, unauthorized mutation, command or expression injection,
path escape, cross-origin credential leakage, provenance or report tampering,
unsafe workflow permissions, a false passing foundational gate, or a material
loss of assessment integrity. The most serious findings are those reachable in
GitHub Actions or reusable-action consumers and those that can alter a trusted
release or leadership result without visible evidence.

Ordinary wording disputes, threshold proposals, documentation typos, and
quality defects without a security impact should use the normal contribution
or support route. A GitHub or other third-party service outage is not a defect
in this repository, although unsafe handling of that outage may be reportable.

## Known limitations and compensating controls

- The default assessment token is intentionally repository-scoped and
  read-only. Administrative or security evidence that it cannot access remains
  `Unknown` unless a separately governed read-only credential is supplied.
- This repository is maintained by one named individual and does not yet have
  a backup owner. Pull-request ingress, the required validation check, immutable
  action pins, Main protection, and private vulnerability reporting are the
  current compensating controls.
- Version `0.1.0-draft` is diagnostic and has not completed the documented
  12-repository calibration pilot. Its grade must not be represented as a
  certification or release decision.
- Public disclosure timing and remediation decisions are coordinated through
  the private advisory. No issue or finding is considered accepted risk unless
  an accountable owner records that decision explicitly.
