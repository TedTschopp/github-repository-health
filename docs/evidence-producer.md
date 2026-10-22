# Repository Health Evidence Producer

**Producer version:** 0.1.0

**Statement schema:** `repository-health-evidence-statement/v1`

**Integration status:** Producer, exact-Main policy selection, and bounded collector are integrated into assessment facts and the evidence inventory; producer outcomes are not yet mapped into assessment controls or scores

This package lets a repository's existing CI, security, release, or deployment job describe an outcome without giving the repository-health assessor permission to run that work. It emits canonical JSON and a SHA-256 manifest. The assessor uses a policy read from exact Main to select an explicit run-and-unit population, and the bounded collector independently validates candidate packages. The resulting audit evidence can appear in the assessment, but collecting or verifying a statement does not currently change a measurement, control, gate, or score; it does not currently change a repository-health score.

## Trust boundary

The producer is a serializer and validator, not an assessor or runner.

- The caller owns the build, test, scan, package, release, or deployment operation and determines its explicit `result`.
- The producer validates identities, syntax, completeness, content digests, timestamp, and internal consistency. It does not discover or infer success.
- The producer does not execute repository build, test, scan, release, deployment, hook, or application code. Its composite action imports only the reviewed producer module in Python isolated mode.
- A valid producer statement proves only that the supplied record is well-formed. The collector must independently bind the repository, unit, subject, workflow, run, source record, and category policy before treating a candidate as observed.
- The assessor authorizes collection only through `.github/repository-health-evidence-policy.json` read from the exact assessed Main commit. A policy from the working tree, another branch, or the producer package cannot authorize itself.
- The workflow definition, pinned action revision, runner, caller outcome mapping, digest-generation method, source system, and artifact retention remain inside the evidence trust zone and must be reviewed accordingly.
- Missing identity, categories, subject digest, source evidence IDs, or explicit result causes creation to fail. `unknown` is a valid explicit result; omitted data is never converted to `success`.

Release and deployment success additionally require at least one artifact SHA-256 digest. Validation and security statements may omit artifact digests when they assess only the bound source subject.

## Statement contract

Every statement contains exactly these top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Exact `repository-health-evidence-statement/v1` contract. |
| `statement_id` | `sha256:` content ID recalculated over every other canonical field. Exact duplicate statements therefore have the same ID and bundles reject repeated IDs. |
| `repository` | Exact case-preserved GitHub `owner/name`. |
| `unit_id` | Controlled deployable or publishable unit identifier. Evidence for one unit cannot satisfy another unit. |
| `subject` | Full Git ref, exact lowercase 40-character Git SHA, and one or more named SHA-256 subject digests. |
| `workflow` | Repository-qualified workflow ref, exact workflow SHA, positive run ID, and positive run attempt. |
| `observed_at` | Canonical UTC ISO 8601 instant ending in `Z`; offset-free and unreasonably future times are rejected. |
| `kind` | `validation`, `security`, `release`, or `deployment`. |
| `result` | Explicit `success`, `failure`, or `unknown`. |
| `categories` | Sorted, non-empty controlled identifiers such as `build`, `unit-test`, `sast`, or `production-promotion`. |
| `artifact_digests` | Sorted named SHA-256 digests; mandatory for successful release and deployment statements. |
| `source_evidence_ids` | Sorted, non-empty IDs for the check, scan, attestation, release, deployment, or other caller evidence supporting the result. |
| `producer` | Fixed producer name/version and `producer_invoked_assessed_code: false`. This is scoped only to the producer, not to other job steps. |

Unknown fields, duplicate JSON keys, duplicate categories, duplicate digest names, duplicate source IDs, non-finite numbers, unsafe identifiers, noncanonical ordering, mismatched content IDs, ambiguous refs, and mismatched expected GitHub identities fail validation.

A digest record has exactly this form:

```json
{"algorithm":"sha256","name":"source-input","value":"<64 lowercase hexadecimal characters>"}
```

Names are logical identifiers, not paths. The bounded collector currently recognizes these exact source ID forms:

- `github-actions-run:<run-id>:<run-attempt>`
- `github-check-run:<check-run-id>`
- `github-release:<release-id>`
- `github-deployment-status:<deployment-id>:<status-id>`
- `github-pages-deployment:<pages-deployment-id>`

Other system-qualified IDs may be serialized, but remain Unknown until a controlled resolver exists. A GitHub Actions run ID is not a check-run ID. Do not place tokens, secrets, personal data, or unredacted findings in an ID.

## Composite action integration

The action lives at [`.github/actions/repository-health-evidence/action.yml`](../.github/actions/repository-health-evidence/action.yml). Run it after the repository's own outcome-producing step. It binds the statement to GitHub's immutable context variables rather than accepting repository, subject SHA, workflow SHA, run ID, or attempt as caller overrides.

The caller must provide:

1. an explicit kind and result;
2. non-empty categories;
3. at least one SHA-256 digest of the exact source input that the job assessed;
4. any output artifact digests required for the claim; and
5. IDs that locate the retained source evidence.

The producer writes `evidence-statement.json` and `SHA256SUMS`. Upload is opt-in and uses a full-SHA-pinned official upload action. The default is local files only.

A centrally referenced, full-SHA-pinned action is the preferred trust boundary because GitHub installs it outside the assessed workspace. A local copied action is easier to trial but can be changed by an earlier workspace-mutating step; treat that possibility as a caller-side evidence limitation.

This bounded example assumes the calling workflow has already computed the exact digest and source evidence ID as outputs of its own reviewed steps:

```yaml
- name: Validate repository
  id: validation
  run: ./your-reviewed-validation-command

# This is a local path only after the producer package has been copied into
# the repository. A central action reference must instead end in a reviewed,
# full 40-character commit SHA; never use @main or a mutable version tag.
- name: Package validation evidence
  if: ${{ always() }}
  uses: ./.github/actions/repository-health-evidence
  with:
    unit-id: application-api
    kind: validation
    result: ${{ steps.validation.outcome == 'success' && 'success' || steps.validation.outcome == 'failure' && 'failure' || 'unknown' }}
    categories-json: '["build","unit-test"]'
    subject-digests-json: >-
      [{"algorithm":"sha256","name":"validation-input","value":"${{ steps.validation-input.outputs.sha256 }}"}]
    artifact-digests-json: '[]'
    source-evidence-ids-json: '["github-actions-run:${{ github.run_id }}:${{ github.run_attempt }}"]'
    upload-artifact: 'true'
    retention-days: '30'
```

`always()` makes a failure/unknown statement possible; it does not make a failed job successful. If the workflow uses `continue-on-error` so evidence can be packaged, a later caller-owned step must restore the intended job failure. The producer does not alter job disposition.

For central reuse, use an immutable reference of this form after the producer exists at that reviewed revision:

```yaml
uses: TedTschopp/github-repository-health/.github/actions/repository-health-evidence@REPLACE_WITH_REVIEWED_FULL_40_CHARACTER_SHA
```

## Command-line integration

The same standard-library module can be invoked without the composite action:

```bash
python3 -m automation.repository_health.evidence_producer create \
  --repository OWNER/REPOSITORY \
  --unit-id application-api \
  --subject-ref refs/heads/main \
  --subject-sha 0123456789012345678901234567890123456789 \
  --subject-digest source-input=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --workflow-ref OWNER/REPOSITORY/.github/workflows/validate.yml@refs/heads/main \
  --workflow-sha 1234567890123456789012345678901234567890 \
  --run-id 123456789 \
  --run-attempt 1 \
  --kind validation \
  --result success \
  --category build \
  --category unit-test \
  --source-evidence-id github-actions-run:123456789:1 \
  --output evidence-statement.json \
  --manifest SHA256SUMS

python3 -m automation.repository_health.evidence_producer validate \
  --input evidence-statement.json \
  --manifest SHA256SUMS \
  --expected-repository OWNER/REPOSITORY \
  --expected-unit-id application-api \
  --expected-subject-sha 0123456789012345678901234567890123456789 \
  --expected-workflow-sha 1234567890123456789012345678901234567890
```

The validator's expected-identity arguments are important at a transfer boundary: the values inside the statement cannot authenticate themselves.

## Result semantics

`result` means the outcome reported by the named source system for the stated categories and exact subject. It is not a repository-health control rating.

- `success`: the caller has affirmative source evidence for successful completion. It must be supplied explicitly.
- `failure`: the caller has affirmative source evidence for failure.
- `unknown`: the job ran or evidence packaging occurred, but the caller cannot make a defensible success/failure claim.

For security jobs, `success` means the security operation completed under its named policy. It must not be interpreted as “no vulnerabilities” unless the category, source record, policy, population, and finding disposition actually establish that conclusion.

## Exact-Main policy and run selection

The integrated assessor loads `RH-EVIDENCE-POLICY-1.0` from `.github/repository-health-evidence-policy.json` at the exact Main SHA. The strict policy binds the repository and unit to one evidence kind, exact sorted categories, a workflow path, `assessed-main` or `production-unit` subject source, allowed events, and `latest-completed-exact-subject` selection. Its in-memory form records the Main SHA, repository path, and SHA-256 of the exact policy bytes.

For example:

```json
{
  "schema_version": "RH-EVIDENCE-POLICY-1.0",
  "repository": "OWNER/REPOSITORY",
  "units": [
    {
      "unit_id": "application-api",
      "statements": [
        {
          "kind": "validation",
          "categories": ["build", "unit-test"],
          "workflow_path": ".github/workflows/validate.yml",
          "subject_source": "assessed-main",
          "events": ["push"],
          "selection": "latest-completed-exact-subject"
        }
      ]
    }
  ]
}
```

Selection uses `RH-ACTIONS-RUN-POPULATION-1.0` to prove what was searched. The current scheduled collector emits a complete `branch-window` for Main, which can cover `assessed-main`. A production tag or other production ref requires a targeted `exact-subjects` population containing the exact ref and SHA; a Main branch window cannot be reused as proof that the production subject was completely searched.

The selector emits `RH-EVIDENCE-POLICY-SELECTION-1.0` and retains eligible runs, derived category policy, selected run identities, policy provenance, and every gap. A run must be completed, have a conclusion, match the exact subject SHA, workflow identity, ref, and event, carry positive integer run and attempt IDs, and be the unique newest terminal match. Missing or partial history, an uncovered subject, no matching run, a timestamp tie, or selecting more than one evidence kind into the same run/unit artifact name yields Unknown. The selector assigns no assurance and applies no score mapping.

## Bounded collector contract

The read-only collector implementation is `automation/repository_health/evidence_artifacts.py`. It validates evidence candidates and returns `RH-EVIDENCE-ARTIFACTS-1.0`; it does not map categories to measures or apply a control result or score.

The integrated selector supplies an explicit authoritative `eligible_runs` population: each run ID maps to the controlled unit IDs for which evidence is expected. For direct library use, the caller must supply an equivalently controlled population. For every explicit run/unit pair, the collector lists only the exact artifact name `repository-health-evidence--<unit_id>` and completes pagination within declared caps. It does not scan a repository's lifetime artifact history and does not assume API sort order. A missing, expired, inaccessible, page-capped, or otherwise incomplete run/unit population remains Unknown, and every candidate from an incomplete population remains Unknown.

The composite action derives that exact artifact name from its already-required `unit-id`; consumers cannot override it. The per-unit suffix lets one workflow run upload independent evidence for multiple units without reusing an artifact name. Each downloaded ZIP is treated as untrusted input and must contain exactly `evidence-statement.json` and `SHA256SUMS`. ZIP count, entry size, expanded size, and total download size are bounded. Absolute paths, traversal, backslashes, symlinks, encrypted entries, duplicates, and extra files are rejected without extraction or execution.

GitHub's artifact download endpoint returns a short-lived redirect. The collector sends credentials only to the configured HTTPS GitHub API origin, strips them on cross-origin requests, bounds the redirect chain, and permits only controlled GitHub Actions or documented Azure artifact hosts for GitHub.com. Unknown hosts, IP literals, embedded credentials, non-HTTPS destinations, and enterprise cross-origin destinations without an explicit policy are rejected. `size_in_bytes` is used only as a pre-download cap because it is artifact metadata, not proof of the exact ZIP transfer length; the bounded response length and any available GitHub artifact digest are validated separately.

The collector independently checks four things:

1. **Package and run identity.** Repository, `unit_id`, subject SHA, workflow path/ref/SHA, run ID, and attempt must agree with the eligible population, artifact metadata, and authoritative Actions run. The common REST run shape `path: .github/workflows/file.yml@main` is accepted only for constrained same-revision events where run head SHA, workflow SHA, and statement subject SHA are identical. Other event shapes need an exact authoritative referenced-workflow binding or remain Unknown.
2. **Result source.** Every supported source ID is joined to its authoritative record. A valid Actions run can support its recorded result, but it cannot authorize arbitrary categories. Deployment evidence additionally requires its authoritative payload to bind the exact unit and artifact digest population. The Pages form uses the one documented Pages deployment ID and exact `/pages/deployments/<id>` status object; there is no invented Pages status ID. That status can corroborate `succeed`, but it exposes neither subject SHA nor content digest, so both bindings remain false and the candidate remains Unknown unless a future controlled record establishes the missing relationship. Release evidence requires the exact controlled release-asset population and an immutable release tag authoritatively peeled to the statement subject SHA; mutable `target_commitish` alone is never accepted.
3. **Category policy.** The integrated assessor derives a controlled policy keyed by unit and kind from the exact-Main evidence policy, with the exact allowed category list and workflow refs. A direct caller must provide the equivalent controlled mapping. This is evaluated separately from result-source validity and defaults to unverified.
4. **Population integrity.** Duplicate artifact IDs, duplicate statement IDs, conflicting claims, and evidence for an ineligible unit remain visible and unresolved. Conflict grouping includes `unit_id`, so independent units in the same run are not pooled.

A category-policy entry has this shape:

```json
{
  "application-api": {
    "validation": {
      "categories": ["build", "unit-test"],
      "workflow_refs": ["OWNER/REPOSITORY/.github/workflows/validate.yml@refs/heads/main"]
    }
  }
}
```

For a deployment source, the authoritative deployment `payload` must use the same canonical `repository-health-deployment-artifact-binding/v1` contract consumed by the delivery collector. It binds one unit and one immutable artifact. The object and nested `artifact` object reject missing or extra keys; `reference` is retained exactly as supplied and must be a bounded, nonempty, control-character-free string; `sha256` must be 64 lowercase hexadecimal characters and must equal the statement's single artifact digest. The delivery resolver separately joins that exact reference to the production-identity selector. The former `repository-health-deployment-artifacts/v1` payload with an `artifact_digests` array is incompatible and remains Unknown.

```json
{
  "schema_version": "repository-health-deployment-artifact-binding/v1",
  "unit_id": "application-api",
  "artifact": {
    "reference": "ghcr.io/example/application-api@sha256:<digest>",
    "sha256": "<64 lowercase hexadecimal characters>"
  }
}
```

### Collector-owned statement verification

After package, run, source, result, artifact, category-policy, population, duplicate, and conflict checks, the collector internally projects eligible candidates to `RH-EVIDENCE-STATEMENT-VERIFICATION-1.0`. A projection records the statement, repository, unit, and source SHA; the matched authoritative source IDs; separate completeness booleans for population, source, result, artifact, and category policy; and `verified`, `unknown`, or `conflict` state.

This projection is generated only inside the trusted collector invocation and can be exposed in the assessment for audit. It is not an accepted input file: a producer ZIP, repository configuration, external adapter, or copied JSON object cannot self-assert the verification. The collector bundle explicitly retains `assurance_assigned: false` and `score_mapping_applied: false`. The assessment evidence inventory may label a bundle E3 when at least one collector-owned projection is verified, but that label applies to the evidence record only. A metric-specific resolver must still establish that the controlled category and complete source population answer a particular measurement before any control or score can change.

These constraints follow GitHub's documented [workflow artifact API](https://docs.github.com/en/rest/actions/artifacts?apiVersion=2026-03-10), [workflow run fields](https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2026-03-10), [Pages deployment status API](https://docs.github.com/en/rest/pages/pages?apiVersion=2026-03-10#get-the-status-of-a-github-pages-deployment), [workflow context variables](https://docs.github.com/en/actions/reference/workflows-and-actions/variables), and [runner communication destinations](https://docs.github.com/en/actions/reference/runners/github-hosted-runners). The collector still produces candidate evidence only. A separate, reviewed resolver must decide whether the controlled category and source population satisfies a measurement before any control assurance or score can change.
