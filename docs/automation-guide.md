# Automated Repository Health Assessment Guide

**Standard assessed:** 0.1.0-draft

**Automation status:** Diagnostic preview

**Enforcement status:** Not a release or compliance gate

This guide explains how the repository-health automation collects evidence, applies the existing standard, and creates reports for engineers and nontechnical leaders. The automation is a supporting assessor. It does not replace the normative [Repository Health Standard](repository-health-standard.md), [Control Catalog](control-catalog.md), [Measurement Dictionary](measurement-dictionary.md), or [Scoring, Assurance, and Exceptions](scoring-assurance-exceptions.md).

The automation follows one governing rule: **absence of evidence is Unknown, not healthy**. A GitHub setting, repository file, or declared configuration is credited only to the assurance level it actually demonstrates.

## Quick start

### Run this standards repository

This repository already contains the local composite action, declaration, and scheduled workflow. After the files are committed to the default branch, enable GitHub Actions and either wait for the daily schedule or start **Repository health assessment** from the Actions page with `workflow_dispatch`.

The scheduled workflow is [.github/workflows/repository-health.yml](../.github/workflows/repository-health.yml). It invokes the action in [.github/actions/repository-health/action.yml](../.github/actions/repository-health/action.yml) and reads [.github/repository-health.toml](../.github/repository-health.toml). When present, production and workflow-evidence policy files are read from the exact assessed Main revision rather than the working tree.

### Use a centrally maintained action

1. Publish this full repository—automation, catalog, and supporting documents—to an approved internal GitHub repository.
2. Select and review a commit, then use its full 40-character SHA as the action reference.
3. Copy [the conservative configuration](../examples/config/repository-health.toml) to `.github/repository-health.toml` in the repository to assess.
4. Copy [the consumer workflow](../examples/workflows/repository-health.yml) to `.github/workflows/repository-health.yml`.
5. Replace `YOUR-ORGANIZATION/repository-health-standard` and `REPLACE_WITH_FULL_COMMIT_SHA` in the workflow.
6. Complete only the declarations supported by current evidence, list the exact authoritative check names for Main, and start a manual run.
7. Review both Markdown reports and the structured JSON before relying on the standing or action order.

The consumer workflow intentionally pins the central action by commit. GitHub recommends treating third-party action workflows as code and supports full-length commit SHAs as the immutable reference. See [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use).

GitHub Enterprise Server requires an internally reachable copy of the action repository. `actions/upload-artifact@v4` and later are not supported on GitHub Enterprise Server, so replace that upload step with the artifact mechanism supported by the installed server version. The evaluator itself uses `GITHUB_API_URL` and can query the current server when the token has access.

### Run the evaluator locally

Python 3.11 or newer is required. From the repository root:

```bash
python3 -m automation.repository_health assess \
  --repository . \
  --catalog docs/control-catalog.md \
  --config .github/repository-health.toml \
  --output repository-health-report/repository-health-assessment.json

python3 -m automation.repository_health.reporting \
  --assessment repository-health-report/repository-health-assessment.json \
  --output-dir repository-health-report
```

Local collection does not call GitHub unless a repository identity and token are supplied. A local working tree can differ from Main; the assessment records the checkout/Main relationship and cleanliness so that uncommitted files are not silently represented as pushed evidence.

## 1. What runs

```mermaid
flowchart LR
    A["Repository files and Git history"] --> C["Read-only evidence collector"]
    B["GitHub APIs and repository configuration"] --> C
    P["Exact-Main production and evidence policies"] --> C
    W["Existing outcome workflows"] --> X["Schema-bound evidence artifacts"]
    X --> C
    C --> N["Fail-closed evidence normalizer"]
    N --> M["Versioned metric calculations"]
    M --> D["35-control evaluator"]
    D --> E["Structured assessment JSON"]
    E --> F["Detailed health assessment"]
    E --> G["Leadership summary"]
    G --> H["Ordered next seven actions"]
    F --> I["Workflow artifact"]
    G --> J["GitHub run summary"]
```

The package contains:

- A standard-library Python evaluator under `automation/repository_health/`.
- A reusable composite action under `.github/actions/repository-health/`.
- A scheduled and manually triggered workflow under `.github/workflows/`.
- A consumer workflow example under `examples/workflows/`.
- A conservative TOML configuration whose defaults create Unknown results rather than invented assurance.
- A bounded evidence producer, exact-Main authorization policy, deterministic Actions-run selector, and untrusted-artifact collector.

No collector invokes the assessed repository's build, test, deployment, hook, application, or remediation commands. Existing CI and delivery systems remain responsible for producing those results; the collector reads the evidence they retain.

## 2. Generated reports

Each successful run produces these files:

| Artifact | Audience | Purpose |
| --- | --- | --- |
| `repository-health-assessment.json` | Tools, assessors, auditors | Complete structured facts, evidence, control dispositions, dimensions, gates, score, assurance, findings, limitations, and separate DORA data. |
| `health-assessment.md` | Engineering and repository owners | Detailed assessment with traceability from every result to evidence and limitations. |
| `leadership-summary.md` | Nontechnical leaders | Plain-language standing, what it means, and the next actions in priority order. |
| `leadership-summary.json` | Portfolio reporting | Compact machine-readable standing and ordered action list. |

The leadership summary never presents the grade by itself. It includes evidence confidence, foundational weaknesses, and up to seven distinct actions. If fewer than seven genuine gaps exist, it reports only the work that is actually needed.

### 2.1 Attested release evidence

The repository's separate [release workflow](../.github/workflows/release.yml) runs only for immutable version tags matching the documented `vMAJOR.MINOR.PATCH[-prerelease]` form. Before publishing, it verifies that the tagged commit is reachable from Main and that the exact commit has a successful `Validate repository` check.

The workflow builds a revision-bound source archive, a file-level SPDX 2.3 SBOM, a revision-and-artifact identity record, and `SHA256SUMS`. The builder reads the correspondence contract from the exact tagged configuration and refuses an `Unknown` or N/A contract. GitHub's artifact-attestation action binds the archive digest and SBOM statement to the publication-workflow identity. Normal publication runs from the tag; guarded recovery runs from Main and records that signer ref separately from the tagged artifact source. The release is created only after all five records are complete, and repository-level immutable releases then lock the published assets and tag against deletion or update.

The release path is intentionally separate from the read-only assessor. Its verification and build job has only `contents: read` and `checks: read`; it transfers checksummed evidence to a second job. Only that isolated publisher receives `contents: write`, `attestations: write`, and `id-token: write`, and it never checks out or executes repository code. The assessment action remains read-only.

After fetching an existing version tag, rebuild its records locally without publishing them:

```bash
python3 -m automation.repository_health.release \
  --repository . \
  --revision v0.1.0-draft \
  --tag v0.1.0-draft \
  --source-repository https://github.com/TedTschopp/github-repository-health \
  --output-directory release-dist
```

The workflow fixes the runner family and Python patch; the identity also records the Git and Python toolchain. Matching bytes demonstrate same-toolchain repeatability, not universal cross-toolchain reproducibility. Local generation does not prove GitHub publication or attestation. Production correspondence is established only when the protected tag, release assets, digests, source identity, and GitHub attestation all agree.

For this repository, the current unit, resolver, exact published identity, evidence digests, and supersession rules are controlled in the machine-readable [production identity record](../.github/repository-health-production.json) and explained in the [release and production correspondence record](release-and-production.md). Those records declare the resolver; they do not replace live verification of the release, tag, checksums, Main reachability, intervening Main validation, or attestations.

Normal publication is tag-triggered. A guarded `workflow_dispatch` input accepts an existing protected version tag only for recovery from an interrupted or failed tag run. It rebuilds that tag's exact revision and applies the same Main-reachability, authoritative-check, tag/version/SHA, checksum, attestation, and existing-release safeguards; it cannot move the tag or replace a published release.

## 3. Evidence boundaries

### 3.1 Evidence the action can collect directly

Depending on token access and repository configuration, the action can observe:

- the Main-role ref and exact revision;
- Git history, branch and tag inventory, activity, and contributor count;
- repository files such as README, ownership, support, security, contribution, license, changelog, dependency, lock, and workflow files;
- GitHub repository and default-branch metadata;
- workflow definitions and every statically visible `uses` dependency, including recursively referenced local actions;
- exact-revision check results plus paginated Actions runs, attempts, and jobs over the metric windows;
- Main commits, associated pull requests, reviews, actors, final revisions, releases, remote refs, tag objects, release assets, deployments, environments, attestations, and visible security results;
- effective branch rules, ruleset details, and visible branch-protection state; and
- explicit, evidence-backed repository profile and control inputs from the TOML file.

Collectors retain population completeness, pagination, source, exact-SHA binding, and every inaccessible endpoint. The normalizer then creates metric-specific assertions only when the required classifications can be made without guessing. These observations do not automatically prove production state, effective bypass behavior, release provenance, vulnerability disposition, operational recovery, or portfolio uniqueness.

The assessment contains one repository-level result for each implemented metric and a result for each declared deployable unit. Repository aggregation uses the worst applicable unit; an Unknown unit makes the repository result Unknown. The detailed Markdown report shows state, threshold band, value, assurance, sample class, coverage, evidence IDs, and limitations before the control table.

### 3.2 Evidence that normally requires another system

The following commonly remain Unknown until supplied from their system of record:

- current production or published identity for every deployable unit;
- artifact digests and source-to-artifact-to-deployment lineage;
- effective permissions, inherited rules, bypass use, and audit-log completeness;
- dependency and vulnerability findings with disposition and due dates;
- rollback, restore, withdrawal, or supersession exercises;
- incident, support, and operational-readiness evidence;
- authoritative portfolio and duplicate-repository records; and
- reliable application- or service-level DORA outcomes.

Use a control override only when the referenced evidence meets the catalog requirement. A written assertion normally establishes E1; current configuration can establish E2; demonstrated operation requires E3; and sustained effectiveness requires E4.

### 3.3 Inaccessible GitHub evidence

The workflow's normal `GITHUB_TOKEN` is intentionally read-only and repository-scoped. Some detailed protection, secret-scanning, membership, and administration endpoints require permissions that the standard workflow token does not provide. A `403` or `404` is recorded as an evidence gap, never interpreted as an absent or passing control. A successful empty page counts as No Events only when the complete eligible population and the measurement dictionary's carry rule are both established.

Organizations that require deeper configuration evidence should use a narrowly scoped GitHub App or fine-grained token under their credential policy. Supplying a more privileged token expands visibility; it does not grant the action permission to change repository state.

### 3.4 Schema-bound workflow evidence

Existing validation, security, release, and deployment workflows can package their explicit result with the [Evidence Producer](evidence-producer.md). The assessor does not search arbitrary artifacts or trust a producer statement by itself. It first loads `.github/repository-health-evidence-policy.json` from the exact assessed Main commit. That policy authorizes one controlled workflow, event set, evidence kind, exact category set, and subject source for each unit.

The Actions collector supplies a versioned population contract. For `assessed-main`, the current scheduled assessment requires a complete Main branch window. For `production-unit`, a complete targeted exact-subject population is required; the Main-only collection does not satisfy that requirement. Within a covered population, the selector chooses the one uniquely newest completed run whose workflow, event, ref, and SHA match the policy and whose run ID and attempt are valid positive integers. Missing policy, inaccessible or capped pages, an uncovered subject, an ambiguous newest run, or an artifact-name collision yields Unknown.

Only the exact `repository-health-evidence--<unit_id>` artifact is downloaded for an eligible run/unit pair. The collector treats the ZIP as untrusted, verifies its bounded two-file package, then independently joins repository, unit, subject, workflow, run, result source, artifact identity, and category policy to authoritative records. Collector-owned statement verifications are generated only inside that invocation; a repository cannot supply a verification object to authenticate itself.

The integrated assessor records selection, candidate packages, verifications, and gaps under `facts.github.produced_evidence` and in the evidence inventory. A fully verified statement can support E3 for that evidence record, but the statement still does not change a measure, control rating, foundational gate, or score. That requires a separate controlled resolver for the exact metric and source population. This boundary prevents a successful job label from becoming a broad self-attested pass.

## 4. Repository configuration

The default location is `.github/repository-health.toml`. The evaluator requires Python 3.11 or newer because it uses the standard-library TOML parser.

Two optional machine-readable contracts complement the TOML configuration:

- `.github/repository-health-production.json` declares exact per-unit selectors using legacy `RH-PRODUCTION-IDENTITY-1.0` or generic `RH-PRODUCTION-IDENTITY-2.0`. See [Production Identity and Delivery Resolution](production-identity.md).
- `.github/repository-health-evidence-policy.json` authorizes schema-bound workflow evidence using `RH-EVIDENCE-POLICY-1.0`.

The evaluator reads both from the exact Main Git object. A dirty working-tree edit or policy present only on the assessment branch cannot affect selection. A missing, malformed, contradictory, or unsupported contract is reported as an evidence limitation and cannot establish a pass.

```toml
[standard]
version = "0.1.0-draft"

[repository]
type = "Deployable application"
lifecycle = "Active"
risk_tier = "Elevated"
main_branch = "main"
owner = "Payments Engineering"
methodology = "GitHub Flow/short-lived feature branches"
observed_methodology = "GitHub Flow/short-lived feature branches"
methodology_confidence = "Moderate"
methodology_evidence_ids = ["ARCH-WORKFLOW-2026-03"]
methodology_contradictions = []
authoritative_checks = ["build-and-test", "release-readiness"]
deployable_units = ["payments-api"]
production_correspondence = "Releasable-Main"

# Each applicability flag accepts true, false, auto, or unknown.
has_current_output = true
publishes_artifacts = true
has_dependencies = "auto"
has_automation = "auto"
has_proposed_change_validation = "auto"
multi_contributor = "auto"
supported = true
has_critical_paths = true
has_produced_artifacts = true
automated_deployment = true
operated_service = true
portfolio_managed = true
has_work_refs = "auto"

[assessment]
observation_days = 90
low_activity_days = 365
assessor = "repository-health automation"
reviewer = "Payments architecture reviewer"
next_review = "2026-11-09"

[methodology_axes]
canonical_integration_topology = "One shared Main role"
change_ingress = "Short-lived branch pull requests"
branch_purpose_and_lifetime = "Change branches removed after integration"
integration_cadence = "Continuous"
release_source = "Immutable revisions reachable from Main"
promotion_mechanism = "Artifact promotion"
parallel_support = "No supported parallel release line"
control_placement = "GitHub rules and required checks"
repository_topology = "Shared canonical repository"

[dora]
available = false
reason = "Product-level deployment data is maintained outside GitHub."
```

`auto` permits a conservative inference from observable repository facts. `unknown` states that the assessment cannot determine the fact. A declared `false` value affects applicability analysis but does not, by itself, constitute an approved N/A determination.

### 4.1 Evidence-backed control input

Use a control table when reliable evidence is available outside the collector:

```toml
[controls."RRO-02"]
conformance = "Met"
assurance = "E3"
rationale = "The recovery exercise completed successfully for every current production unit."
evidence_ids = ["OPS-RECOVERY-2026-07"]
```

The evaluator rejects an override without a rationale and evidence reference. The input does not override the catalog's minimum assurance. A temporary risk waiver remains visible and does not turn an Unmet or Unknown control into Met.

An N/A disposition also requires an approver:

```toml
[controls."SPI-02"]
conformance = "N/A"
assurance = "E2"
rationale = "The repository has no deployed, published, distributed, applied, or supported output."
evidence_ids = ["PORTFOLIO-NO-OUTPUT-2026-08"]
n_a_approved_by = "Enterprise Architecture"
n_a_approved_at = "2026-08-09"
n_a_review_date = "2026-11-07"
```

The assessor remains responsible for confirming that the catalog actually permits N/A for the stated scope.

### 4.2 Production identity integration boundary

The legacy release profile remains supported for this standards repository. The generic v2 validator supports application deployments, packages, GitOps refs, documentation publication, approved no-current-output decisions, and archive/retirement dispositions without inferring a methodology from a branch name.

Generic v2 is currently groundwork, not an alternate route to a G-02 pass. A selector-bound collector can construct resolver-ready facts for controlled application deployments, package releases, GitOps refs, and GitHub Pages publications, and the pure fail-closed delivery resolver is available for controlled integration testing. The assessment engine does not yet map that complete type-specific delivery and evidence path into `M-SPI-02S` or the score. A syntactically valid selector, successful deployment status, governance declaration, or producer statement therefore remains insufficient by itself. Unsupported or incomplete adapters remain Unknown.

### 4.3 Optional DORA outcome input

DORA inputs are accepted only as a complete, separately evidenced service-level panel. They never affect repository scoring.

```toml
[dora]
available = true
service = "payments-api"
period_start = "2026-05-01"
period_end = "2026-07-31"
evidence_ids = ["DELIVERY-METRICS-2026-Q2"]
context = "Customer-facing API; planned weekday releases."
limitations = "Emergency manual releases are reconciled the next business day."

[dora.metrics.change_lead_time]
value = "18 hours median; 44 hours p85"
unit = "hours"
source = "delivery analytics export"
formula = "production deployment time minus first commit time; median and p85"
coverage = "100 percent of 36 production changes"
limitations = "Batch releases can include more than one change."

[dora.metrics.deployment_frequency]
value = "12 per month"
unit = "production deployments per month"
source = "deployment system"
formula = "successful production deployments divided by months observed"
coverage = "100 percent of production deployment records"
limitations = "Reports the service as a whole, not this repository alone."

[dora.metrics.failed_deployment_recovery_time]
value = "41 minutes median"
unit = "minutes"
source = "deployment and incident systems"
formula = "recovery time minus failed-deployment start time; median"
coverage = "100 percent of four failed deployments"
limitations = "Small sample; interpret as Low Sample."

[dora.metrics.change_fail_rate]
value = "8 percent"
unit = "percent"
source = "deployment and incident systems"
formula = "deployments requiring immediate intervention divided by production deployments"
coverage = "100 percent of production deployment records"
limitations = "Uses the service's approved intervention classification."

[dora.metrics.deployment_rework_rate]
value = "6 percent"
unit = "percent"
source = "delivery work records"
formula = "deployment effort correcting earlier deployments divided by total deployment effort"
coverage = "96 percent of classified deployment effort"
limitations = "Four percent of effort was not classifiable and was not imputed."
```

When `available = false`, supply a plain-language `reason`. Do not estimate missing deployment outcomes from pull requests, commits, or repository activity.

## 5. Scoring and action ordering

The evaluator uses the unchanged 0.1.0-draft rules:

- Met = 1, Partially met = 0.5, and Unmet or Unknown = 0.
- Each applicable control is equally weighted within its dimension.
- Each applicable dimension is equally weighted in the overall score.
- A failed or Unknown applicable foundational gate caps the effective result at 69.0/D/M1.
- N/A is excluded only with documented rationale and approval.
- DORA outcomes remain informative and never change the repository-health score.

The leadership action list uses the finding priority from the manual assessment guide:

1. failed or Unknown foundational gates;
2. Critical-tier failures and expired decisions;
3. known high-risk control failures;
4. repeated build, release, security, or operational weakness;
5. evidence gaps preventing a reliable decision; and
6. remaining maintainability and usability improvements.

Within a priority class, the renderer favors the action that removes the broadest risk or unlocks the next decision. It de-duplicates closely related controls so leadership receives seven decisions or investments, not seven variations of the same task.

## 6. GitHub Actions operating model

The standards repository's provided workflow runs daily at a minute offset from the top of the hour and can also be started manually. Daily snapshots support measures that require a W90 daily correspondence population. The conservative consumer example remains weekly until its owner deliberately installs an approved durable-history publisher and records policy. The provided workflow:

1. checks out full Git history without retaining write credentials;
2. selects a supported Python runtime;
3. runs the read-only composite action;
4. appends the leadership brief to the GitHub run summary;
5. uploads the four reports and their evidence-history transfer records as a 90-day workflow artifact; and
6. passes that checksummed artifact to an isolated publisher that appends the assessment to a durable evidence branch.

The action fails only when configuration, catalog parsing, collection, evaluation, or report generation cannot complete. It does **not** fail because a repository has a low score or a foundational weakness. Provisional 0.1.0-draft results must not be used as a release or compliance gate.

Scheduled workflows run from the default branch and may be delayed during periods of GitHub Actions load. Use the manual trigger for an immediate reassessment after material remediation.

The supplied repository publishes durable history only when the assessed workflow ref is `refs/heads/main`. A manual run on another branch may produce the ordinary diagnostic artifact, but it cannot enter the privileged publisher. Repositories whose Main role uses another branch name must change that condition deliberately when installing the workflow.

GitHub documents that scheduled workflows run on the default branch and can be delayed during high-load periods, especially near the start of the hour. See [Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

### 6.1 Composite-action inputs

| Input | Default | Purpose |
| --- | --- | --- |
| `repository-path` | `.` | Checked-out repository to assess. |
| `config-path` | `.github/repository-health.toml` | Repository declaration and evidence references. |
| `output-directory` | `repository-health-report` | Destination for the four stable reports. |
| `github-repository` | Current `${{ github.repository }}` | Optional `owner/name` override. |
| `github-token` | Empty | Read-only token for visible GitHub evidence. The example passes `${{ github.token }}`. |

The action exposes report paths plus raw/effective score, grade, maturity, active-cap state, assurance, assessment ID, history-candidate path, checksum path, and controlled snapshot path as outputs. It appends only the leadership Markdown to `GITHUB_STEP_SUMMARY`; artifact upload and retention remain explicit workflow-owner decisions. GitHub job summaries are backed by the per-step `GITHUB_STEP_SUMMARY` file; see [Adding a job summary](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/workflow-commands-for-github-actions#adding-a-job-summary).

### 6.2 Token permissions and inaccessible settings

The workflow grants no permissions at workflow scope. Its assessor job receives only `actions: read`, `attestations: read`, `checks: read`, `contents: read`, `deployments: read`, `pages: read`, `pull-requests: read`, `security-events: read`, and `statuses: read`. These are read scopes; inaccessible products and endpoints remain Unknown. Its separate history-publisher job receives only `contents: write`; it has no assessed-source checkout or Python setup and does not invoke assessed build, test, deploy, hook, or application code. The protected workflow definition remains executable trust-zone code. The automatic `GITHUB_TOKEN` is repository-scoped and expires when each job ends. See [Automatic token authentication](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication).

GitHub's detailed branch-protection endpoint requires administration read permission. The normal workflow does not elevate itself to obtain that access; an inaccessible response remains Unknown. See [Branch protection REST API](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection).

### 6.3 Durable evidence history

The ordinary workflow artifact remains available for 90 days and contains the detailed assessment, both leadership reports, the machine-readable leadership summary, `history-candidate.json`, and `HISTORY_SHA256SUMS`. The checksum manifest names only those controlled transfer files. Before publication, the writer rejects missing files, symlinks, unexpected manifest paths, duplicate entries, digest or size mismatches, unsafe assessment IDs, path traversal, and provenance that does not identify the current workflow run and assessed revision.

Durable records live on the dedicated `repository-health-evidence` branch, separate from Main and product source; its first publication may create a root commit with no Main parent. Each successful run adds exactly one snapshot at:

```text
evidence/snapshots/YYYY/MM/<assessment_id>.json
```

The snapshot embeds the machine-readable assessment, report digests and sizes, source and workflow commit identities, run identity and URL, and the SHA-256 digest of the preceding snapshot's exact bytes. `evidence/latest.json` points to the current snapshot and repeats its exact byte digest. A reader can therefore detect a changed snapshot, a missing link, a duplicate identity, an orphaned/conflicting record, or a latest pointer that disagrees with the chain. Run `python3 -m automation.repository_health.history validate <checked-out-evidence-branch>` for an offline validation; it performs no network calls.

The publisher obtains the current evidence-branch head, refuses an existing snapshot path, creates the snapshot and latest pointer in one Git tree, and advances the ref with `force: false`. A stale head, concurrent write, non-fast-forward update, malformed history tip, or API ambiguity fails the run without replacing history. Protect the evidence branch from force pushes, deletion, and writes by actors other than the designated workflow; the hash chain detects mutation but does not prevent an independently authorized administrator from rewriting Git history.

Repository and organization Actions policy must permit the job's requested `contents: write` scope. If it does not, publication fails closed and the 90-day report artifact remains available for investigation; the workflow does not fall back to a broader personal token.

This layout also provides the W365 measurement-history path. Before calculating trends, the read-only assessor resolves the evidence-branch commit and tree through the Git Data API, loads controlled snapshot paths within bounded byte/count limits, validates the latest pointer and every link in the selected segment, and only then supplies prior assessments to the normalizer. When the branch contains more than the bounded download population, the first selected snapshot's predecessor digest is retained as an opaque anchor: the assessor may establish a complete daily W365 window without claiming that the older prefix or an all-time chain was validated. A missing evidence branch is recorded as complete `no_history`, not as passing history; an inaccessible, partial, oversized, malformed, internally gapped, or conflicting selected segment supplies no snapshots and leaves dependent trends Unknown. The offline reader applies full-chain validation to a checked-out evidence branch.

## 7. Security and privacy

- Keep workflow-level permissions empty, keep assessment scopes read-only, protect the workflow definition, and isolate the single `contents: write` history append in a job that never checks out the assessed tree or invokes assessed build, test, deploy, hook, or application code. For stronger separation, move publication to a centrally owned pinned workflow or a GitHub App credential constrained to the evidence branch.
- Prefer a GitHub App or fine-grained token over a broadly scoped personal token when additional evidence access is required.
- Pin external actions to reviewed immutable revisions.
- Do not place secrets, confidential logs, regulated data, or raw vulnerability details in configuration, workflow summaries, or artifacts.
- Store evidence references and immutable identifiers rather than sensitive evidence copies.
- Treat repository files and API responses as untrusted input when rendering Markdown; the reporter escapes or normalizes unsafe content.
- Apply records policy independently to the 90-day report artifact and durable evidence branch; do not assume Git branch retention replaces an approved records schedule.

## 8. Interpretation and limitations

An automated result can be useful before it is complete. A low score dominated by Unknown controls usually means leadership should first fund evidence access and ownership, not assume that every underlying practice is failing. Conversely, a configured setting at E2 does not prove sustained effectiveness.

The report must retain this disclosure:

> This automated assessment uses the provisional Git Repository Health Standard 0.1.0-draft. It is an improvement diagnostic, not a compliance certification or release gate. Automated collection is limited to the evidence sources and permissions listed in the report; Unknown does not mean failed, and configured does not mean demonstrated effective.

The real 12-repository, two-assessor calibration pilot remains required before the standard or automated evaluator can be described as enterprise-calibrated.
