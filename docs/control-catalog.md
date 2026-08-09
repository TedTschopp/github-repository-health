# Repository Health Control Catalog

**Status:** Provisional 0.1.0-draft

**Effective for pilot use:** 2026-08-09

**Next standards review:** 2027-02-09

**Companion documents:** [Repository Health Standard](repository-health-standard.md), [Measurement Dictionary](measurement-dictionary.md), [Scoring, Assurance, and Exceptions](scoring-assurance-exceptions.md), and [Source Register](source-register.md)

## 1. Purpose and use

This catalog defines evidence-based outcomes for healthy Git repositories without mandating one branching methodology, hosting platform, or release cadence. Requirements use the BCP 14 meanings of **MUST**, **SHOULD**, and **MAY**. External sources support the controls, but the normative requirements and provisional thresholds below are owned by this standard.

Assess the deployable unit first and aggregate to a repository only after every unit has been assessed. A monorepo can therefore have more than one result. Use the ten canonical types in the [Classification Guide](classification-guide.md#2-repository-type-classification): Deployable application, Library/package, Monorepo, Infrastructure-as-code/GitOps, Data/analytics/model, Documentation/content, Template/scaffold, Sandbox/experimental, Mirror/fork, and Archived/retired.

### 1.1 Risk tiers

- **Baseline:** the universal minimum for every in-scope repository, including stable-supported, experimental, mirrored, archived, and retired repositories under type- and lifecycle-specific applicability. It covers limited-blast-radius contexts without material safety, regulatory, privileged-access, or sensitive-data consequence and with straightforward recovery.
- **Elevated:** the [standard's Elevated criteria](repository-health-standard.md#4-risk-tiers), such as a production service, broadly consumed package, shared platform, confidential data, material financial or operational impact, or difficult recovery.
- **Critical:** the [standard's Critical criteria](repository-health-standard.md#4-risk-tiers), such as safety- or mission-critical operation, privileged infrastructure or security controls, regulated high-impact data, very broad blast radius, or severe recovery constraints.

The [Repository Health Standard](repository-health-standard.md#4-risk-tiers) is authoritative for tier assignment. Higher tiers inherit lower-tier requirements. Assessors record the impact rationale and do not infer a tier from contributor count or methodology alone. `N/A` is permitted only where a control lists an applicability exclusion and the assessment records evidence for that exclusion.

### 1.2 Evidence states and exceptions

- **Pass:** the evidence minimum exists, is fresh, and meets the threshold.
- **Concern:** evidence exists but falls in the concern band.
- **Fail:** evidence establishes nonconformance.
- **Unknown:** the required evidence is absent, inaccessible, stale, or internally inconsistent. Unknown is never treated as Pass.
- **N/A:** a documented applicability exclusion, approved by the repository owner, applies.
- **Exception:** a time-bounded deviation records scope, rationale, risk, compensating control, accountable owner, approver, and expiry. An exception does not manufacture evidence, alter Pass/Concern/Fail/Unknown, remove an observation from a denominator, or lift a gate cap. Approved equivalent controls and approved N/A determinations are separate decisions, not exceptions.

Every control declares a **Minimum assurance** level from E1 through E4. A Pass may map to Met only when evidence reaches that floor under the scoring guide; evidence below the floor is rated no higher than the scoring guide permits. The floor is part of the control, not an assessor-selected weight. Stable low-activity repositories use the Classification Guide's extended-window and approved stable-state evidence procedure; sparse events alone do not create a failure.

Each control earns points exactly once and only in its catalog dimension. A cross-domain reference may create or inform a linked finding, and evidence may independently determine a foundational gate, but neither creates duplicate control points. The only catalog grade caps in provisional 0.1.0-draft are the documented G-01 through G-04 caps; external organizational governance decisions are reported separately and do not silently modify this score.

The four foundational gates are G-01 through G-04. A gate that is **Fail** or **Unknown** caps the provisional overall grade at **D**. Gate waivers, if governance permits them, remain visible and do not alter the underlying evidence state.

## 2. Foundational gates

| Gate | Enforcing control | Required outcome |
|---|---|---|
| G-01 | SPI-01 | Main is buildable, validated, and releasable under the repository type and support contract at the exact assessed revision. |
| G-02 | SPI-02 | Every current production, published, distributed, or supported output is traceable to an immutable source revision reachable from Main. |
| G-03 | CGD-01 | Every accepted change has a controlled, attributable, validated, and auditable path to Main, including recorded bypass use. |
| G-04 | CGD-02 | Main and every production-critical ref are protected against unauthorized change, deletion, and history rewriting. |

## 3. SPI — Source-to-production integrity

### SPI-01 — Main validity and buildability

- **Gate:** G-01.
- **Tier/applicability:** Baseline, Elevated, Critical; every repository, including mirrors, sandboxes, and archived repositories under its type-specific contract. For non-code repositories, “build” means the declared authoritative validation, rendering, schema, integrity, synchronization, or archival-readability check. For an archive, “releasable” means that retained source/output can be reconstructed or its non-releasable disposition is explicitly validated under the archive contract.
- **Normative statement:** The exact HEAD revision of Main **MUST** have successful authoritative build and validation results and **MUST** satisfy the type-specific releasability or disposition contract; the repository **MUST NOT** knowingly leave Main in a failed state.
- **Intent:** Preserve Main as a trustworthy integration line from which the repository's output can be produced or validated.
- **Acceptable patterns/equivalents:** Merge queue; pre-merge validation plus post-merge verification; direct-trunk pre-submit gate; deterministic document/data validation; a clean-room build for a package or service.
- **Evidence/evidence minimum:** Main ref and SHA; required-check policy; successful terminal result bound to that SHA; build/validation log; declared validation command; and release/package/render/synchronization/readability evidence required by the type-specific contract. Minimum is one fresh, successful result for the exact current SHA and proof that build, validation, and releasability/disposition assertions are authoritative.
- **Linked measure:** M-SPI-01 (Main validity state) and M-SPI-01T (Main invalid-duration trend).
- **Threshold:** M-SPI-01 must be Pass. M-SPI-01T is Pass at no more than 1% invalid time, Concern above 1% through 5%, and Fail above 5% in the observation window.
- **Unknown/N-A/exception treatment:** Missing, stale, skipped, neutral, or SHA-mismatched results are Unknown. N/A is not allowed; archives use their type-specific contract in addition to RLP-03. Exceptions remain gate-visible and do not change the state.
- **Grade effect:** Scored once in SPI using the worst applicable threshold band across M-SPI-01 and M-SPI-01T; a documented No Events result for M-SPI-01T carries the M-SPI-01 band and does not create an extra point. G-01 is determined only by M-SPI-01; Fail or Unknown caps the overall grade at D.
- **Minimum assurance:** E3 — Demonstrated; current exact-revision execution must prove the type-specific build, validation, and releasability/disposition outcome.
- **Remediation:** Define one authoritative validation path, run it on the exact Main SHA, make it required, and repair or revert the breaking change.
- **Owner/review date:** Repository technical owner; standard steward Repository Health Council; review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-008, SRC-009, SRC-010, and SRC-013.

### SPI-02 — Production and publication traceability

- **Gate:** G-02.
- **Tier/applicability:** Baseline, Elevated, Critical whenever any current output is deployed, published, applied, distributed, or has a supported operational consumer. Applicability is evaluated independently per deployable unit, including units in archived repositories.
- **Normative statement:** Each current production, published, distributed, applied, or supported output **MUST** identify an immutable source revision reachable from Main and the immutable artifact or content identity derived from that revision.
- **Intent:** Make “what is in production” a verifiable fact instead of an inference from branch names.
- **Acceptable patterns/equivalents:** Deployment record containing commit SHA and artifact digest; immutable release tag plus package digest; GitOps applied commit; static-site publication record; model/data release manifest.
- **Evidence/evidence minimum:** Current output and supported-consumer inventory; deployment/publication/distribution record; immutable source revision; proof that the revision is reachable from Main; artifact/content digest or immutable identifier; status and timestamp. Minimum is a complete evidence chain for every applicable unit.
- **Linked measure:** M-SPI-02S (current traceability state) and M-SPI-02 (traceability rate).
- **Threshold:** M-SPI-02S must be 100%. M-SPI-02 is Pass at 100%, Concern from 95% to below 100%, and Fail below 95%.
- **Unknown/N-A/exception treatment:** A branch name, mutable `latest` tag, version string without commit linkage, unreachable revision, or undocumented manual assertion is Unknown. N/A requires current evidence that the unit has no production, publication, distribution, applied state, or supported operational consumer; historical output alone does not prevent N/A.
- **Grade effect:** Scored once in SPI using the worst applicable threshold band across M-SPI-02S and M-SPI-02; a documented No Events result for M-SPI-02 carries the M-SPI-02S band and does not create an extra point. G-02 is determined only by M-SPI-02S; Fail or Unknown caps the overall grade at D.
- **Minimum assurance:** E3 — Demonstrated; current runtime/registry evidence must resolve the complete output-to-artifact-to-Main chain for every applicable unit.
- **Remediation:** Record the deployed revision and immutable artifact identity at release/deploy time; reconcile all current environments and publications.
- **Owner/review date:** Release owner and repository technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-005, SRC-011, SRC-019, and SRC-020.

### SPI-03 — Immutable release identity and provenance

- **Tier/applicability:** Elevated and Critical; Baseline for repositories that publish reusable artifacts.
- **Normative statement:** Released artifacts and release labels **MUST** be immutable, uniquely identifiable, and linked to verifiable build or publication provenance appropriate to the risk tier.
- **Intent:** Prevent a named release from silently changing and allow consumers to verify its origin.
- **Acceptable patterns/equivalents:** Protected immutable Git tag; package version that cannot be overwritten; artifact digest with SLSA provenance; signed release manifest; immutable content-addressed publication.
- **Evidence/evidence minimum:** Release identifier; immutable source SHA; artifact digest; provenance or build record; tag/package immutability configuration. Minimum is one-to-one identity for every release sampled in the window.
- **Linked measure:** M-SPI-03 (immutable release identity coverage).
- **Threshold:** Pass at 100%; Concern from 95% to below 100%; Fail below 95% or when any currently supported release has been overwritten.
- **Unknown/N-A/exception treatment:** N/A is allowed when no currently supported release/publication exists and no eligible release occurred in the observation window; archive-only historical retention is assessed under RLP-03. Mutable convenience aliases are permitted only when an immutable identity is also recorded. Unverifiable immutability is Unknown.
- **Grade effect:** Scored only in SPI; no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; immutable identity and provenance/build linkage must be shown on actual releases.
- **Remediation:** Protect release tags, disable version overwrite, capture digests, and generate provenance at build/publication time.
- **Owner/review date:** Release owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-005, SRC-019, and SRC-020.

### SPI-04 — Declared production-correspondence contract

- **Tier/applicability:** Elevated and Critical; Baseline when an output is deployed or published.
- **Normative statement:** The repository **MUST** declare and continuously evidence one production-correspondence contract—Exact-Main, Releasable-Main, Production-Ref, or a per-unit combination—and **MUST** surface drift from that contract.
- **Intent:** Support valid methodologies while making the relationship among Main, release refs, artifacts, and runtime state explicit.
- **Acceptable patterns/equivalents:** Exact-Main (`production SHA == Main HEAD`); Releasable-Main (production SHA is an ancestor of Main and intervening commits passed required gates); Production-Ref (declared protected environment/version ref equals production and resolves to a revision reachable from Main); component-level contracts in monorepos.
- **Evidence/evidence minimum:** Declared contract per deployable unit; Main and production SHAs; Main-reachability plus contract-specific ancestry/equality proof; required-check results for any ahead commits; drift alert or assessment record. Minimum is a current resolved relation for every unit.
- **Linked measure:** M-SPI-04 (production-correspondence compliance).
- **Threshold:** Pass at 100%; Concern from 95% to below 100% over the window while current state conforms; Fail below 95% or whenever current state violates the contract.
- **Unknown/N-A/exception treatment:** Undeclared contract or missing runtime identity is Unknown. N/A follows SPI-02. A multi-version product must enumerate every supported production version rather than select one favorable ref.
- **Grade effect:** Scored only in SPI. The same evidence is evaluated separately against SPI-02 when current production identity is not trustworthy; this control earns no duplicate points.
- **Minimum assurance:** E3 — Demonstrated; representative current and historical evidence must show the declared correspondence contract operating on actual output state.
- **Remediation:** Select the appropriate contract, document it per unit, capture exact identities, and reconcile or explicitly retire drifted deployments.
- **Owner/review date:** Release owner and service/product owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-011, SRC-014, SRC-015, and SRC-016.

## 4. BTC — Build, test, and CI health

### BTC-01 — Authoritative automated build or validation

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories.
- **Normative statement:** The repository **MUST** define a non-interactive, version-controlled process that creates or validates its deliverable from a clean checkout using declared inputs.
- **Intent:** Make successful creation of the output repeatable by someone other than the original author.
- **Acceptable patterns/equivalents:** Build script; package task; container build; IaC validate/plan; documentation build/link check; data schema validation; hermetic build service.
- **Evidence/evidence minimum:** Version-controlled command/workflow; declared toolchain and inputs; clean execution log; produced artifact or validation result. Minimum is one successful clean run within the metric sample.
- **Linked measure:** M-BTC-01 (automated build replay success rate).
- **Threshold:** Pass at 100% of the last ten eligible replays, Concern at 90% to below 100%, Fail below 90%.
- **Unknown/N-A/exception treatment:** No eligible replay is Unknown. N/A is not allowed for active repositories; the validation may be lightweight but must be explicit.
- **Grade effect:** Scored only in BTC; current failure is also evaluated against G-01 without adding a second BTC point.
- **Minimum assurance:** E3 — Demonstrated; at least one actual clean replay must establish that the declared process works.
- **Remediation:** Capture the build/validation process in version control, declare toolchain versions, remove undocumented local prerequisites, and replay from a clean checkout.
- **Owner/review date:** Repository technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-005, and SRC-008.

### BTC-02 — Per-change CI coverage

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories.
- **Normative statement:** Every proposed and accepted change to Main **MUST** trigger the applicable automated build and validation suite on the final revision without manual initiation.
- **Intent:** Detect defects before or immediately after integration and retain evidence for the exact accepted content.
- **Acceptable patterns/equivalents:** Pull-request CI; merge queue; pre-submit gate; trusted pre-receive validation for direct trunk; post-merge verification in addition to pre-merge validation.
- **Evidence/evidence minimum:** Change-event inventory; CI trigger configuration; check runs tied to final revisions. Minimum is complete event-to-run linkage for the assessment window.
- **Linked measure:** M-BTC-02 (per-change CI coverage).
- **Threshold:** Pass at 100%; Concern from 95% to below 100%; Fail below 95%.
- **Unknown/N-A/exception treatment:** Changes made during an outage remain in the denominator. Approved documentation-only path exclusions must be declared in the validation matrix; otherwise absent runs are Unknown.
- **Grade effect:** Scored only in BTC; skipped coverage may inform a CGD-04 finding, which is evaluated under its own control without duplicating this control's points.
- **Minimum assurance:** E3 — Demonstrated; representative change-to-run evidence plus current trigger configuration must show automatic coverage in operation.
- **Remediation:** Correct triggers and path filters, make final-revision checks required, and backfill verification for accepted changes lacking evidence.
- **Owner/review date:** CI owner and repository technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-008, SRC-009, and SRC-010.

### BTC-03 — Risk-based validation matrix

- **Tier/applicability:** Baseline, Elevated, Critical; validation categories scale with repository type and risk.
- **Normative statement:** The repository **MUST** declare the validation categories required for each change class and **MUST** execute all applicable categories before acceptance.
- **Intent:** Avoid both a one-size-fits-all test mandate and unexamined gaps in high-risk changes.
- **Acceptable patterns/equivalents:** Unit/integration/acceptance tests; lint/type/schema checks; security scans; IaC policy checks; documentation render/accessibility/link checks; data-quality tests; manual evidence only where automation is infeasible and explicitly approved.
- **Evidence/evidence minimum:** Version-controlled validation matrix; change classification; check results; approved manual evidence where applicable. Minimum is a category result for every required category on each sampled change.
- **Linked measure:** M-BTC-03 (required validation-category satisfaction).
- **Threshold:** Pass at 100%; Concern from 95% to below 100%; Fail below 95% or any skipped Critical-tier category. An exception records accepted risk but does not remove the failed category or automatic Fail condition.
- **Unknown/N-A/exception treatment:** A category may be N/A only through the matrix's documented applicability rule. Missing classification or path-filter rationale is Unknown.
- **Grade effect:** Scored only in BTC; no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; representative final-revision evidence must show each applicable validation category operating as declared.
- **Remediation:** Define change classes and required categories, close path-filter gaps, automate frequent checks, and govern unavoidable manual validation.
- **Owner/review date:** Quality owner and repository technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-004, and SRC-009.

### BTC-04 — CI feedback latency

- **Tier/applicability:** Baseline, Elevated, Critical; all repositories with proposed-change validation.
- **Normative statement:** Required CI **SHOULD** return actionable terminal feedback within the repository's declared service-level objective (SLO).
- **Intent:** Keep validation fast enough that contributors integrate small changes rather than batch work or bypass checks.
- **Acceptable patterns/equivalents:** Parallel test stages; tiered fast/slow checks; merge queue; cached but integrity-protected dependencies; repository-specific SLO approved for inherently long tests.
- **Evidence/evidence minimum:** CI start/end timestamps for all required checks; declared SLO and rationale. Minimum is a 90-day sample or the last 30 completed changes, whichever provides more observations.
- **Linked measure:** M-BTC-04 (p95 required-feedback latency).
- **Threshold:** Pass at p95 no greater than the declared SLO, Concern above 1.0 through 2.0 times the SLO, Fail above 2.0 times; default SLO is 30 minutes when none is approved.
- **Unknown/N-A/exception treatment:** Fewer than five observations are reported as Low Sample, not N/A; absent timestamps or SLO are Unknown.
- **Grade effect:** Scored only in BTC; no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; representative comparable timing evidence must establish feedback performance against the declared SLO.
- **Remediation:** Profile the critical path, remove redundant work, parallelize, right-size runners, and separate non-blocking long tests without weakening required risk coverage.
- **Owner/review date:** CI owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-009 and SRC-015.

### BTC-05 — Validation reliability

- **Tier/applicability:** Baseline, Elevated, Critical; all repositories with automated validation.
- **Normative statement:** Required checks **MUST** be deterministic enough that rerunning the same source and configuration does not routinely change the outcome.
- **Intent:** Preserve trust in failures and prevent habitual reruns from becoming an unofficial bypass.
- **Acceptable patterns/equivalents:** Flake detection; quarantine with owner and expiry; deterministic fixtures; isolated test environments; controlled retries that retain the initial failure signal.
- **Evidence/evidence minimum:** Check attempts grouped by source SHA and configuration identity; rerun outcomes; quarantine register. Minimum is outcome history for the observation window.
- **Linked measure:** M-BTC-05 (flaky outcome-change rate).
- **Threshold:** Pass at no more than 1%; Concern above 1% through 3%; Fail above 3%.
- **Unknown/N-A/exception treatment:** Rebuilds with changed code, dependencies, or configuration are not reruns. No automated checks is Fail under BTC-01/BTC-03, not N/A here. Unlinkable reruns are Unknown.
- **Grade effect:** Scored only in BTC; no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; representative comparable rerun evidence, or enabled retry capture with no reruns, must establish the measured reliability state.
- **Remediation:** Identify unstable checks, fix isolation/timing/data causes, quarantine only with expiry, and prevent rerun-only success from satisfying required status.
- **Owner/review date:** Quality owner and CI owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-009.

## 5. CGD — Change governance and branch discipline

### CGD-01 — Controlled and auditable path to Main

- **Gate:** G-03.
- **Tier/applicability:** Baseline, Elevated, Critical; every repository, including mirrors, sandboxes, and archives under their type-specific synchronization, locked-change, or retained-history contract.
- **Normative statement:** Every change accepted into Main **MUST** pass a declared controlled path that records the final revision, actor, authorization, required validation result, acceptance event, and any bypass or privileged path used.
- **Intent:** Make Main changes attributable and policy-enforced across pull-request, direct-trunk, fork, patch, and hybrid methodologies.
- **Acceptable patterns/equivalents:** Approved PR/MR; merge queue; pre-receive-controlled direct trunk with review record; signed patch accepted by an integration manager; trusted release automation with constrained identity.
- **Evidence/evidence minimum:** Main change inventory; proposal or direct-change record; identity; final revision; authorization/review evidence; required checks; merge/push event; bypass classification; and, when bypassed, reason, affected control, incident/change link, approval or retrospective review, and access expiry where applicable. Minimum is a complete audit chain for every sampled Main change.
- **Linked measure:** M-CGD-01 (audited Main-change coverage).
- **Threshold:** Pass at 100%; Concern is not available for the current gate state; any incomplete accepted change is Fail. The historical percentage is retained for trend.
- **Unknown/N-A/exception treatment:** Unavailable audit logs or inability to enumerate Main changes is Unknown. N/A is not allowed. Break-glass and other bypass changes remain in the denominator; an exception does not complete a missing audit field.
- **Grade effect:** Scored once in CGD. G-03 Fail or Unknown caps the overall grade at D.
- **Minimum assurance:** E3 — Demonstrated; representative accepted-change evidence plus current enforcement must show the controlled path, including bypass accountability, in operation.
- **Remediation:** Declare one accepted path, enforce it at the source-control boundary, preserve event logs, and reconcile unlinked changes.
- **Owner/review date:** Repository administrator and technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-004, SRC-005, SRC-010, and SRC-013.

### CGD-02 — Protection of production-critical refs

- **Gate:** G-04.
- **Tier/applicability:** Baseline, Elevated, Critical; Main plus every active production, release, maintenance, environment, immutable release, GitOps, or other production-critical ref. Archived repositories include Main and retained refs whose integrity preserves supported or historical state.
- **Normative statement:** Main and all production-critical refs **MUST** prevent unauthorized direct update, deletion, and history rewriting and **MUST** enforce the repository's required acceptance controls.
- **Intent:** Protect the refs whose compromise could change accepted or released content.
- **Acceptable patterns/equivalents:** Branch/ruleset protection; protected tags; server-side hooks; signed integration by a constrained bot; environment-ref policies; access controls with audited emergency bypass.
- **Evidence/evidence minimum:** Complete critical-ref inventory; effective protection configuration including overlapping rules; permission and bypass lists; a tested enforcement result. Minimum is every required protection assertion for every critical ref.
- **Linked measure:** M-CGD-02 (critical-ref protection coverage).
- **Threshold:** Pass only at 100%. Any missing assertion or unassessed matching-rule interaction is Fail or Unknown respectively.
- **Unknown/N-A/exception treatment:** N/A is not allowed for Main. Release/environment refs may leave scope only after documented EOL. Configuration inaccessible to the assessor is Unknown, not assumed protected.
- **Grade effect:** Scored once in CGD. G-04 Fail or Unknown caps the overall grade at D.
- **Minimum assurance:** E3 — Demonstrated; effective protection and bypass behavior must be exported and tested for every critical ref.
- **Remediation:** Inventory critical refs, apply effective least-privilege rules, disable deletion/force push, require acceptance checks, and test rule precedence.
- **Owner/review date:** Repository administrator and security owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-005, SRC-006, SRC-010, and SRC-013.

### CGD-03 — Independent review of final changes

- **Tier/applicability:** Elevated and Critical; Baseline SHOULD comply when two trusted people are available.
- **Normative statement:** An independent trusted person **MUST** approve the final accepted revision for Elevated repositories; Critical repositories **MUST** meet their declared two-party review policy. The change author **MUST NOT** satisfy the independent approval.
- **Intent:** Reduce accidental and malicious changes and ensure someone besides the author understands the accepted content.
- **Acceptable patterns/equivalents:** PR/MR approval; synchronous pair review with durable attribution; integration-manager sign-off; SLSA Source two-party review; a narrowly defined trusted-robot rule only when approved as an equivalent control that satisfies the same outcome and evidence threshold.
- **Evidence/evidence minimum:** Final revision identity; author/uploader; reviewer identities; approval timestamp and context; stale-approval behavior. Minimum is proof that approval covers the final content.
- **Linked measure:** M-CGD-03 (independent final-review coverage).
- **Threshold:** Pass at 100%; Concern from 95% to below 100%; Fail below 95% or any unreviewed Critical-tier human change.
- **Unknown/N-A/exception treatment:** Baseline single-maintainer repositories may record N/A with ownership evidence and compensating validation. Elevated/Critical single-maintainer cases remain nonconforming even when a time-bounded Exception accepts the risk. Bot review alone is not independent human review; only a documented equivalent control may change applicability.
- **Grade effect:** Scored only in CGD; no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; representative final-revision evidence must show valid independent review in operation.
- **Remediation:** Require final-revision approval, dismiss stale approvals or require last-push approval, add qualified reviewers, and narrow bot exceptions.
- **Owner/review date:** Engineering manager or maintainer lead; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-005, SRC-006, SRC-010, and SRC-013.

### CGD-04 — Enforced required checks

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories.
- **Normative statement:** Acceptance controls **MUST** prevent a change from entering Main or another critical ref unless every applicable required check succeeds on the final revision.
- **Intent:** Turn validation policy into an enforced boundary rather than an advisory convention.
- **Acceptable patterns/equivalents:** Required status checks; merge queue; pre-receive hook; protected bot integration; signed policy attestation verified before acceptance.
- **Evidence/evidence minimum:** Required-check configuration; final-revision results; acceptance events; bypass behavior. Minimum is platform-enforced proof across all sampled changes.
- **Linked measure:** M-CGD-04 (required-check enforcement coverage).
- **Threshold:** Pass at 100%; any accepted change lacking enforced final-revision required checks is Fail. Attempted omissions that were blocked are reported as control-effectiveness evidence but are not denominator failures.
- **Unknown/N-A/exception treatment:** Advisory checks, manually inspected badges, or checks on an earlier revision are not equivalent. N/A is not allowed for active repositories.
- **Grade effect:** Scored only in CGD. The result may inform a BTC finding without duplicate points; when an accepted change lacked required validation, G-03 also fails.
- **Minimum assurance:** E3 — Demonstrated; current configuration and representative accepted-change evidence must show required-check enforcement in operation.
- **Remediation:** Bind checks to protected refs and final revisions, close bypass paths, and verify merge-queue or direct-trunk enforcement.
- **Owner/review date:** Repository administrator and CI owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-006, SRC-010, and SRC-013.

### CGD-05 — Methodology-conformant branch and merge behavior

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories after classification as Trunk-based, GitHub Flow/short-lived feature branches, GitFlow, Environment-branch flow, Release train/multi-version maintenance, GitOps promotion, Fork/integration-manager, Direct gated trunk, or Custom/hybrid.
- **Normative statement:** The repository **MUST** declare its integration and release topology and **SHOULD** conform to the corresponding branch-lifetime, merge-direction, cleanup, and fix-propagation rules.
- **Intent:** Grade disciplined execution of the chosen methodology instead of grading preference for one methodology.
- **Acceptable patterns/equivalents:** Any canonical profile above; a custom profile that explicitly defines source refs, target refs, promotion mechanism, owner-approved cadence basis and branch/fix/cleanup SLOs, release refs, fix direction, reconciliation behavior where applicable, and deletion/EOL rules.
- **Evidence/evidence minimum:** Workflow declaration; declared delivery cadence; owner and approval date for cadence-relative branch/fix/cleanup/reconciliation SLOs; branch/ref history; PR/MR or patch events; tags/releases; promotion/reconciliation records; cherry-pick/backport links; current reconciliation-obligation inventory; profile-specific event classification. Minimum is complete coverage of every applicable profile rule in the selected window and every current release-line fix obligation.
- **Linked measure:** M-CGD-05 (methodology event-conformance rate) and M-CGD-05B (backport/reconciliation drift).
- **Threshold:** M-CGD-05 is Pass at 95% or higher, Concern from 80% to below 95%, and Fail below 80% or when observed topology materially contradicts the declared production path. M-CGD-05B is Pass at 0% overdue drift, Concern above 0% through 5%, and Fail above 5% or for any overdue Critical-tier obligation.
- **Unknown/N-A/exception treatment:** A repository may be Custom/hybrid but not Undeclared. Missing cadence basis, owner approval, an applicable profile rule, reconciliation SLO, or complete release-line-fix inventory is Unknown. M-CGD-05B is N/A only when documented topology proves that no supported non-Main production, release, maintenance, environment, or GitOps promotion line can receive fixes. Insufficient event history is Unknown or Low Sample as defined in the dictionary, not a forced methodology label.
- **Grade effect:** Scored once in CGD using the worst applicable threshold band across M-CGD-05 and M-CGD-05B; an N/A M-CGD-05B is excluded and neither linked measure creates an extra point. A contradiction may inform an SPI-04 finding, which is evaluated under its own control without duplicating this control's points.
- **Minimum assurance:** E3 — Demonstrated; representative classified events must show the declared profile contract in operation.
- **Remediation:** Correct the declaration or operating behavior, shorten/retire branches as appropriate, and document intentional hybrid rules.
- **Owner/review date:** Maintainer lead; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; profile guidance from SRC-012, SRC-014, SRC-015, SRC-016, SRC-017, and SRC-021.

### CGD-06 — Privileged and bypass change accountability

- **Tier/applicability:** Baseline, Elevated, Critical; all repositories whose controls can be bypassed or administered.
- **Normative statement:** Every bypass, force operation, rule change, emergency update, and other privileged change **MUST** be least-privileged, logged, attributable, justified, and reviewed after use.
- **Intent:** Preserve accountability for necessary emergency paths and detect control erosion.
- **Acceptable patterns/equivalents:** Break-glass role; time-bound elevation; audited administrator bypass; controlled service account; emergency patch followed by retrospective review.
- **Evidence/evidence minimum:** Privileged-event inventory; actor; timestamp; affected ref/control; reason and change/incident link; approver or post-event reviewer; expiry where access changed. Minimum is a complete record for every event.
- **Linked measure:** M-CGD-06 (accountable bypass coverage).
- **Threshold:** Pass at 100%; Concern from 95% to below 100%; Fail below 95% or any unattributed Critical-tier event.
- **Unknown/N-A/exception treatment:** Zero events is Pass only when audit logging and event retrieval are demonstrably enabled; otherwise Unknown. N/A applies only when the platform has no bypass capability and that fact is evidenced.
- **Grade effect:** Scored only in CGD; a bypass that defeats a foundational gate also causes that gate to Fail without adding a second CGD point.
- **Minimum assurance:** E3 — Demonstrated; representative privileged-event evidence plus retrievable audit configuration must show accountability in operation; zero-event handling follows the linked measure.
- **Remediation:** Centralize privileged roles, enable audit logging, require reason fields and time bounds, review events, and remove persistent bypass actors.
- **Owner/review date:** Repository administrator and security owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-004, SRC-005, SRC-010, and SRC-013.

## 6. SSC — Security and software-supply-chain health

### SSC-01 — Secret prevention and response

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories.
- **Normative statement:** The repository and its workflows **MUST** prevent unencrypted credentials and secrets from being accepted where feasible, detect exposures, and require revocation and documented response when exposure occurs.
- **Intent:** Prevent source history and automation logs from becoming credential distribution channels.
- **Acceptable patterns/equivalents:** Pre-receive secret protection; push protection; CI scanning; allowlist with review and expiry; external secret manager; documented history-remediation procedure after revocation.
- **Evidence/evidence minimum:** Prevention/scanning configuration; current and reachable-history scan; verified-finding inventory; response records; reviewed allowlist; preventive-control review date. Minimum is all applicable control assertions, zero unresolved verified live secrets, and control review within 365/180/90 days for Baseline/Elevated/Critical.
- **Linked measure:** M-SSC-01 (secret-control compliance).
- **Threshold:** Pass at 100%; Concern only when the sole unsatisfied assertion is a preventive-control review overdue by no more than 25% of its tier interval and there are zero unresolved verified live secrets; Fail for any other unsatisfied assertion, a review overdue by more than 25%, or any unresolved verified live secret.
- **Unknown/N-A/exception treatment:** N/A is not allowed. A scanner that cannot inspect history must be supplemented or recorded as incomplete. Suspected findings under triage are Unknown until resolved.
- **Grade effect:** Scored only in SSC; no standalone catalog grade cap. External incident-governance decisions are reported separately and do not alter the provisional 0.1.0-draft score.
- **Minimum assurance:** E3 — Demonstrated; fresh current/history scanning and preventive configuration must jointly establish the state.
- **Remediation:** Revoke first, rotate dependent systems, remove or legally expunge content where required, close prevention gaps, and record the incident.
- **Owner/review date:** Security owner and repository technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-004, and SRC-006.

### SSC-02 — Complete dependency inventory

- **Tier/applicability:** Baseline, Elevated, Critical; repositories with direct software, action, image, module, plugin, model, or data dependencies.
- **Normative statement:** Direct dependencies **MUST** be declared in machine-readable manifests or equivalent inventories, and released artifacts at Elevated/Critical tiers **MUST** have a version-linked dependency inventory or SBOM appropriate to the artifact.
- **Intent:** Make dependency risk and release composition discoverable.
- **Acceptable patterns/equivalents:** Lockfile and manifest; container base-image digest inventory; Git submodule declaration; SPDX SBOM; package bill; model/data lineage manifest.
- **Evidence/evidence minimum:** Discovery output; manifests/locks; release-linked inventory/SBOM where applicable; reconciliation report. Minimum is coverage of every discovered direct dependency class.
- **Linked measure:** M-SSC-02 (dependency inventory coverage).
- **Threshold:** Pass at 100%; Concern from 95% to below 100%; Fail below 95% or any untracked privileged build/workflow dependency.
- **Unknown/N-A/exception treatment:** N/A requires a discovery scan showing no external dependencies. Transitive incompleteness is reported separately unless the tier/profile requires a complete SBOM.
- **Grade effect:** Scored only in SSC; no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; a fresh discovery/reconciliation run must cover actual dependency classes and the required release inventory.
- **Remediation:** Add missing manifests/locks, inventory non-language dependencies, produce release-linked SBOMs, and reconcile declared with discovered inputs.
- **Owner/review date:** Dependency steward or technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-006, and SRC-020.

### SSC-03 — Vulnerability and dependency-risk remediation

- **Tier/applicability:** Baseline, Elevated, Critical; repositories with dependencies or produced software artifacts.
- **Normative statement:** Verified vulnerability and dependency-risk findings **MUST** have severity-based remediation targets and accountable owners, **MUST** be remediated or closed by evidenced equivalent control before the target expires, and **MUST** retain documented disposition. Accepted risk records a deviation but does not satisfy remediation.
- **Intent:** Measure whether known actionable risk is managed, rather than merely whether scanners run.
- **Acceptable patterns/equivalents:** Upgrade; patch; remove dependency; an equivalent compensating control that closes the finding with evidence; false-positive disposition with evidence. Time-bounded accepted risk remains visible but does not satisfy remediation.
- **Evidence/evidence minimum:** Fresh vulnerability/dependency scan; finding severity and first-known date; owner; target date; remediation/equivalent-control evidence; disposition; and exception record where present. Minimum is a determinate status for every High/Critical finding; accepted risk remains open for conformance.
- **Linked measure:** M-SSC-03 (overdue High/Critical finding rate).
- **Threshold:** Pass at 0% overdue; Concern above 0% through 5% with no overdue Critical finding; Fail above 5% or any overdue Critical finding. Default targets are 7 days for Critical and 30 days for High unless stricter policy applies.
- **Unknown/N-A/exception treatment:** No applicable dependencies or executable artifact may be N/A with discovery evidence. No fresh scan is Unknown. Accepted risk is reported separately and remains overdue once the remediation target passes, regardless of exception expiry.
- **Grade effect:** Scored only in SSC; no standalone grade cap in 0.1.0-draft.
- **Minimum assurance:** E3 — Demonstrated; fresh finding, ownership, target, and disposition evidence must establish the current state and its trend inputs.
- **Remediation:** Triage findings, prioritize exposed and exploitable paths, upgrade/remove/mitigate, assign owners and dates, and document time-bounded accepted risk.
- **Owner/review date:** Security owner and dependency steward; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-004, and SRC-006.

### SSC-04 — Secure CI/CD workflow configuration

- **Tier/applicability:** Baseline, Elevated, Critical; repositories with automation.
- **Normative statement:** CI/CD workflows **MUST** use least-privilege tokens, isolate untrusted code and metadata from privileged credentials, pin third-party executable dependencies to immutable identities, and protect production secrets.
- **Intent:** Prevent the automation plane from becoming a path to modify source, artifacts, or production.
- **Acceptable patterns/equivalents:** Read-only top-level token permissions with job-level grants; isolated untrusted PR jobs; full commit-SHA pinning; verified internal action registry; environment-scoped secrets released only after policy gates.
- **Evidence/evidence minimum:** Workflow files; effective token permissions; dependency pin inventory; trigger/data-flow analysis; secret/environment policy. Minimum is every applicable assertion for every privileged workflow job.
- **Linked measure:** M-SSC-04 (secure-workflow assertion coverage).
- **Threshold:** Pass at 100%; Concern from 90% to below 100% with no critical dangerous-workflow pattern; Fail below 90% or any path by which untrusted input can access privileged credentials or execute with write authority.
- **Unknown/N-A/exception treatment:** N/A only when no automation exists; that absence does not waive BTC controls. Undetectable inherited organization settings are Unknown unless exported as evidence.
- **Grade effect:** Scored only in SSC; an exploit path that defeats G-03 or G-04 also causes the affected gate to Fail without adding a second SSC point.
- **Minimum assurance:** E3 — Demonstrated; exact-revision workflow analysis plus effective permissions and secret-release evidence must establish every assertion.
- **Remediation:** Minimize permissions, separate trust domains, pin and verify executable dependencies, constrain secrets to protected environments, and remove dangerous trigger/input combinations.
- **Owner/review date:** CI platform owner and security owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-005, SRC-006, SRC-010, and SRC-013.

## 7. OWM — Ownership and maintainability

### OWM-01 — Accountable repository ownership

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories.
- **Normative statement:** The repository **MUST** identify an active technical owner, business/service owner where applicable, support contact, lifecycle state, and risk tier.
- **Intent:** Ensure operational and technical decisions have accountable people or teams.
- **Acceptable patterns/equivalents:** Catalog metadata; repository metadata file; CODEOWNERS plus service catalog; organization-level ownership registry inherited by the repository.
- **Evidence/evidence minimum:** Resolvable owner identifiers; ownership scope; support route; lifecycle and tier declaration; recent confirmation. Minimum is all required fields and a successful identity resolution.
- **Linked measure:** M-OWM-01 (ownership metadata completeness).
- **Threshold:** Pass at 100%; Concern from 80% to below 100% if technical ownership remains valid; Fail below 80% or when no active technical owner resolves.
- **Unknown/N-A/exception treatment:** N/A is not allowed for active repositories. A departed individual or unmonitored mailbox is missing evidence. Inherited ownership must be traceable.
- **Grade effect:** Scored only in OWM; no standalone grade cap.
- **Minimum assurance:** E2 — Configured; current authoritative metadata and successful identity resolution must cover every required field.
- **Remediation:** Assign accountable teams, replace personal-only ownership, register support and lifecycle metadata, and confirm ownership.
- **Owner/review date:** Business/service owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-004, and SRC-018.

### OWM-02 — Critical-path ownership and knowledge resilience

- **Tier/applicability:** Baseline for designated critical paths; Elevated and Critical required.
- **Normative statement:** Security-sensitive, release, infrastructure, data-migration, and other declared critical paths **MUST** have named qualified owners; Elevated and Critical repositories **SHOULD** avoid a single-person ownership dependency.
- **Intent:** Route reviews to competent maintainers and reduce abandonment or key-person risk.
- **Acceptable patterns/equivalents:** CODEOWNERS; ownership manifest; directory/module steward mapping; rotating maintainer group; documented integration-manager hierarchy.
- **Evidence/evidence minimum:** Critical-path inventory; owner mapping; active membership; required reviewer configuration where used. Minimum is at least one owner per Baseline path and two active qualified people or an approved continuity plan per Elevated/Critical path.
- **Linked measure:** M-OWM-02 (critical-path ownership coverage).
- **Threshold:** Pass at 100%; Concern from 90% to below 100%; Fail below 90% or any unowned production/security/release path.
- **Unknown/N-A/exception treatment:** N/A only when the owner confirms no critical paths after documented classification. A team alias with no resolvable active members is Unknown.
- **Grade effect:** Scored only in OWM; no standalone grade cap.
- **Minimum assurance:** E2 — Configured; current path classification, owner mapping, and membership evidence must establish coverage.
- **Remediation:** Identify critical paths, appoint qualified primary and backup owners, update review routing, and document continuity.
- **Owner/review date:** Maintainer lead; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-010, and SRC-013.

### OWM-03 — Maintained toolchain and technical-obligation register

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories.
- **Normative statement:** Supported runtimes, build images, package managers, generators, and material technical-debt or maintenance obligations **MUST** have owners and review or due dates, and overdue obligations **MUST** be visible.
- **Intent:** Distinguish a stable low-change repository from an abandoned repository and prevent invisible toolchain decay.
- **Acceptable patterns/equivalents:** Renovation schedule; dependency-update service; lifecycle dashboard; technical-debt register; periodic clean build; platform support matrix.
- **Evidence/evidence minimum:** Active obligation inventory; component/tool version; support status; owner; next review/due date; disposition. Minimum is a current record for every declared material obligation.
- **Linked measure:** M-OWM-03 (maintenance-obligation freshness).
- **Threshold:** Pass at 100% current; Concern from 90% to below 100%; Fail below 90% or any unsupported Critical-tier build/runtime component. An exception records accepted risk but does not change the result.
- **Unknown/N-A/exception treatment:** Low commit frequency is not a failure. No obligation register is Unknown for Elevated/Critical and may be satisfied at Baseline by current support metadata and a successful clean build.
- **Grade effect:** Scored only in OWM; no standalone grade cap.
- **Minimum assurance:** E2 — Configured; a current, owner-resolved obligation and support-status register must cover the assessed scope.
- **Remediation:** Inventory toolchain and debt obligations, assign owners/dates, retire unsupported components, and schedule periodic clean validation.
- **Owner/review date:** Repository technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-006 and SRC-008.

### OWM-04 — Reviewable source and generated-artifact governance

- **Tier/applicability:** Baseline, Elevated, Critical; all repositories.
- **Normative statement:** The repository **MUST NOT** store generated executable or unreviewable binary artifacts as authoritative source unless a documented necessity, provenance, integrity check, regeneration or update process, and owner are present.
- **Intent:** Keep accepted changes reviewable and prevent source and embedded outputs from silently diverging.
- **Acceptable patterns/equivalents:** Store release artifacts in an artifact registry; Git LFS with provenance for legitimate media/data; checked-in generated source with deterministic regeneration and diff review; vendored binary with documented necessity, verified digest, update process, and owner.
- **Evidence/evidence minimum:** Binary/generated-file inventory; classification; policy; provenance/digest; regeneration or update instructions; owner; and any exception reported separately. Minimum is a conforming disposition for every detected item; an exception alone is not a conforming disposition.
- **Linked measure:** M-OWM-04 (reviewable-artifact compliance).
- **Threshold:** Pass at 100%; Concern from 95% to below 100% with no unexplained executable; Fail below 95% or any unexplained generated executable or privileged binary.
- **Unknown/N-A/exception treatment:** No detected items yields Pass when the scan is fresh. Detection gaps are Unknown. Legitimate media/data are not automatically failures but require classification for Elevated/Critical repositories.
- **Grade effect:** Scored only in OWM; the result may inform an SSC finding without duplicate points and has no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; exact-revision detection and disposition evidence must cover every detected binary/generated item.
- **Remediation:** Move build outputs to a registry, document and verify necessary binaries, add deterministic regeneration, or remove stale artifacts.
- **Owner/review date:** Repository technical owner and security owner for executables; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004 and SRC-006.

## 8. DCR — Documentation and contributor readiness

### DCR-01 — Essential repository orientation

- **Tier/applicability:** Baseline, Elevated, Critical; all active repositories.
- **Normative statement:** The repository **MUST** provide findable, current documentation of purpose, lifecycle/status, intended consumers, prerequisites, basic use, and the authoritative build or validation command.
- **Intent:** Let a new maintainer or assessor determine what the repository is and verify it without private oral knowledge.
- **Acceptable patterns/equivalents:** Root README; generated repository portal linked from README; inherited organizational documentation with stable links and repository-specific overlay.
- **Evidence/evidence minimum:** Documentation containing each required topic; successful link resolution; command verified against current Main. Minimum is all applicable topics and a working validation path.
- **Linked measure:** M-DCR-01 (essential orientation coverage).
- **Threshold:** Pass at 100%; Concern from 80% to below 100%; Fail below 80% or when purpose or validation instructions are absent.
- **Unknown/N-A/exception treatment:** N/A is not allowed for active repositories. Confidential content may link to access-controlled documentation, but access and ownership must be verifiable.
- **Grade effect:** Scored only in DCR; no standalone grade cap.
- **Minimum assurance:** E2 — Configured; current findable documentation and a verified validation path must cover the required topics.
- **Remediation:** Add or refresh orientation topics, replace dead links, and verify commands from a clean checkout.
- **Owner/review date:** Documentation owner or technical owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-008, and SRC-018.

### DCR-02 — Contribution and workflow documentation

- **Tier/applicability:** Baseline, Elevated, Critical; active multi-contributor repositories. Single-maintainer Baseline repositories must at least document their accepted change path.
- **Normative statement:** The repository **MUST** document how to propose, validate, review, integrate, release, backport or fix, and exceptionally bypass a change under its declared methodology.
- **Intent:** Make the actual governance path usable and reviewable by contributors.
- **Acceptable patterns/equivalents:** CONTRIBUTING file; engineering handbook linked from the repository; maintainer guide; patch-submission guide; an overlay for any of the nine canonical profiles, including GitOps promotion and Custom/hybrid.
- **Evidence/evidence minimum:** Workflow topics and links; profile declaration; required checks; reviewer/owner routing; release/fix direction; exception path. Minimum is every applicable workflow topic.
- **Linked measure:** M-DCR-02 (contribution/workflow documentation coverage).
- **Threshold:** Pass at 100%; Concern from 80% to below 100%; Fail below 80% or when the documented acceptance path contradicts enforced behavior.
- **Unknown/N-A/exception treatment:** Public contribution guidance may be N/A for a closed repository, but internal change-path guidance is still required. Unreadable inherited policy is Unknown.
- **Grade effect:** Scored only in DCR; a material contradiction may inform CGD-05, which is evaluated under its own control without duplicating this control's points.
- **Minimum assurance:** E2 — Configured; current workflow documentation must reconcile with exported enforcement configuration.
- **Remediation:** Document the observed workflow, resolve contradictions, include required checks and emergency paths, and link the guide prominently.
- **Owner/review date:** Maintainer lead; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-012, SRC-014, SRC-015, SRC-016, SRC-017, SRC-018, and SRC-021.

### DCR-03 — Support and security reporting routes

- **Tier/applicability:** Baseline, Elevated, Critical; all supported repositories. Public repositories require a public security-reporting route; private repositories may use an internal route.
- **Normative statement:** The repository **MUST** publish resolvable support and private security-reporting routes, expected response behavior, and supported-version or service boundaries.
- **Intent:** Ensure users can report defects and vulnerabilities to a monitored owner without public disclosure of sensitive details.
- **Acceptable patterns/equivalents:** SECURITY.md; support file; issue template plus private advisory/email route; service desk; organization-level policy inherited through a visible link.
- **Evidence/evidence minimum:** Applicable support and private security routes; monitored owner; expected response behavior; supported versions/scope; separate last-verification record for each applicable route. Minimum is successful resolution of every applicable route and freshness within the tier limit.
- **Linked measure:** M-DCR-03 (support/security route coverage and freshness).
- **Threshold:** Pass at 100%; Concern only when every applicable route resolves and the sole deficiency is verification overdue by no more than 25% of its tier interval; Fail when any applicable route is missing/nonfunctional or another assertion is unsatisfied.
- **Unknown/N-A/exception treatment:** A support-route assertion may be N/A only for an archived repository that clearly disclaims support under RLP-03. The entire control is N/A only when the archive has no supported consumer and documented evidence shows no continuing security-response obligation. Otherwise the private security route remains applicable. Approved N/A assertions are removed from both numerator and denominator.
- **Grade effect:** Scored only in DCR; the result may inform an SSC finding without duplicate points and has no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; monitored ownership and successful route tests must establish every applicable assertion.
- **Remediation:** Publish monitored routes, state scope and response expectations, test delivery, and replace personal contacts with durable team channels.
- **Owner/review date:** Support owner and security owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004 and SRC-018.

### DCR-04 — Rights, versioning, and release-change documentation

- **Tier/applicability:** Baseline for rights declaration; Elevated and Critical for released outputs and compatibility commitments.
- **Normative statement:** The repository **MUST** state applicable usage/licensing rights, and released outputs **MUST** document versioning, compatibility, and material changes according to their declared release policy.
- **Intent:** Let consumers understand whether and how they may use the content and what changed between supported releases.
- **Acceptable patterns/equivalents:** Open-source license; internal proprietary-use notice; third-party notice; SemVer for a declared public API; calendar/version policy; changelog; release notes; migration guide.
- **Evidence/evidence minimum:** Rights file/notice; release-version policy; supported versions; release notes/change record; compatibility/migration notes where applicable. Minimum is every applicable documentation element.
- **Linked measure:** M-DCR-04 (rights and release-documentation coverage).
- **Threshold:** Pass at 100%; Concern from 80% to below 100% when rights remain clear; Fail below 80% or when usage rights are absent/ambiguous.
- **Unknown/N-A/exception treatment:** Release-change elements may be N/A for never-released repositories; rights declaration is never N/A. SemVer is required only when explicitly adopted and a public API exists.
- **Grade effect:** Scored only in DCR; no standalone grade cap.
- **Minimum assurance:** E2 — Configured; exact-revision and latest-supported-release documents must cover every applicable item.
- **Remediation:** Add the correct rights notice, declare versioning/support policy, publish release notes, and document breaking-change migration.
- **Owner/review date:** Product owner and legal/license owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-018, and SRC-019.

## 9. RRO — Release, rollback, and operational readiness

### RRO-01 — Complete release evidence

- **Tier/applicability:** Elevated and Critical; Baseline for any repository with a current supported release or an eligible release/deployment/publication in the observation window.
- **Normative statement:** Each release **MUST** preserve a complete evidence record linking approved source, successful build/validation, immutable artifact or content, release authorization, target, status, and material release notes.
- **Intent:** Make release decisions reproducible and auditable independently of ephemeral CI logs.
- **Acceptable patterns/equivalents:** Release object plus provenance; deployment manifest; package publication record; GitOps promotion PR; static publication manifest; signed release dossier.
- **Evidence/evidence minimum:** Required release fields defined in M-RRO-01 for each release in scope. Minimum is a complete record for every current supported release and every release in the window.
- **Linked measure:** M-RRO-01 (release-evidence completeness).
- **Threshold:** Pass at 100%; Concern from 95% to below 100%; Fail below 95% or any current release without source/artifact identity.
- **Unknown/N-A/exception treatment:** N/A when there is no current supported release and no eligible release/deployment/publication in the observation window. Historical evidence retained solely for an archived/retired repository is assessed under RLP-03. Inaccessible evidence for an applicable release is Unknown.
- **Grade effect:** Scored only in RRO; missing current identity also causes G-02 to Fail without adding a second RRO point.
- **Minimum assurance:** E3 — Demonstrated; durable records must resolve every applicable release-field pair.
- **Remediation:** Define a durable release record, capture evidence during the pipeline, retain it for the support period, and reconcile current releases.
- **Owner/review date:** Release owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-005, SRC-011, SRC-019, and SRC-020.

### RRO-02 — Practiced rollback, roll-forward, or withdrawal

- **Tier/applicability:** Elevated and Critical for current operational or supported outputs; Baseline SHOULD comply for current operational outputs.
- **Normative statement:** Each deployable unit **MUST** have a version-appropriate recovery method—rollback, roll-forward, revert, package withdrawal/reissue, infrastructure restore, or content republication—and Elevated/Critical owners **MUST** periodically exercise it.
- **Intent:** Establish that a bad release can be contained and replaced, not merely that a runbook exists.
- **Acceptable patterns/equivalents:** Automated rollback; tested roll-forward hotfix; GitOps revert; database forward-fix with restore drill; package yanking and corrected release; static-content revert.
- **Evidence/evidence minimum:** Recovery procedure; prerequisites; last successful drill or real recovery; result and follow-up actions. Minimum is one successful exercise within the tier interval.
- **Linked measure:** M-RRO-02 (recovery exercise age and result).
- **Threshold:** Pass when the last successful exercise is within 365 days Baseline, 180 days Elevated, or 90 days Critical; Concern up to 1.25 times the interval; Fail beyond that or after a failed exercise without successful retest.
- **Unknown/N-A/exception treatment:** N/A for a never-released experiment or a retired repository/unit with no current deployed, published, distributed, or supported output. A real recovery can satisfy the exercise if evidence and learning are retained. Procedure without exercise is Unknown for applicable Elevated/Critical units.
- **Grade effect:** Scored only in RRO; no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; a successful representative exercise or evidenced real recovery within the tier interval is required.
- **Remediation:** Select the recovery strategy, automate where safe, exercise it in a representative environment, and close findings.
- **Owner/review date:** Service/release owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003 and SRC-008.

### RRO-03 — Controlled production deployment path

- **Tier/applicability:** Elevated and Critical; Baseline for automated deployment/publication.
- **Normative statement:** Production deployment or publication **MUST** accept only authorized source refs or immutable artifacts, protect credentials and targets, enforce declared approvals/policies, serialize conflicting operations where necessary, and retain deployment status/history.
- **Intent:** Extend repository trust through the final production-changing step.
- **Acceptable patterns/equivalents:** Protected environment; GitOps reconciler restricted to an environment branch; package registry publisher with scoped identity; deployment controller verifying provenance; approved manual promotion with durable record.
- **Evidence/evidence minimum:** Deployment configuration; allowed refs/artifacts; identities/permissions; protection rules; concurrency/locking policy where relevant; deployment records. Minimum is every applicable production-control assertion.
- **Linked measure:** M-RRO-03 (production deployment-control coverage).
- **Threshold:** Pass at 100%; Concern from 90% to below 100% with no unauthorized path; Fail below 90% or any path that permits an untrusted ref/artifact to reach production.
- **Unknown/N-A/exception treatment:** N/A only for repositories with no deployment/publication. External deployment systems must export equivalent evidence; inaccessible configuration is Unknown.
- **Grade effect:** Scored only in RRO; the result may inform an SPI finding without duplicate points. An unauthorized path also fails G-02, G-03, or G-04 when the applicable gate outcome is not satisfied.
- **Minimum assurance:** E3 — Demonstrated; effective production-path configuration and durable deployment evidence must establish every assertion.
- **Remediation:** Restrict deployment inputs and identities, add environment protections and provenance verification, serialize collisions, and retain status records.
- **Owner/review date:** Platform/release owner and security owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-005, SRC-010, SRC-011, and SRC-013.

### RRO-04 — Operational readiness evidence

- **Tier/applicability:** Elevated and Critical; Baseline for operated services, infrastructure, data pipelines, or supported published packages.
- **Normative statement:** Before an output is considered production-ready, the owner **MUST** document and verify the applicable health, observability, release-verification, incident, data-recovery/migration, support, and dependency-withdrawal responsibilities.
- **Intent:** Prevent a green build from being mistaken for an operable and supportable release.
- **Acceptable patterns/equivalents:** Service runbook and dashboards; IaC recovery plan; package advisory/yank procedure; model monitoring and rollback; static-site publication verification; release checklist with evidence links.
- **Evidence/evidence minimum:** Applicable readiness matrix; links to current runbooks/monitors/checks; named owners; latest verification. Minimum is every required profile item.
- **Linked measure:** M-RRO-04 (operational-readiness evidence coverage).
- **Threshold:** Pass at 100%; Concern from 80% to below 100%; Fail below 80% or any missing Critical-tier incident/recovery owner.
- **Unknown/N-A/exception treatment:** Individual matrix items may be N/A with profile rationale; the entire control is N/A only for never-released experiments or retired repositories.
- **Grade effect:** Scored only in RRO; DORA outcomes are reported separately and never blended into this health score.
- **Minimum assurance:** E3 — Demonstrated; current operational evidence and verification records must establish every applicable readiness item.
- **Remediation:** Complete the profile-specific readiness matrix, link live operational evidence, assign owners, and verify before the next release.
- **Owner/review date:** Service/product owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-003, SRC-007, and SRC-011.

## 10. RLP — Repository lifecycle and portfolio hygiene

### RLP-01 — Complete portfolio classification

- **Tier/applicability:** Baseline, Elevated, Critical; all repositories, including archived repositories.
- **Normative statement:** The portfolio record **MUST** identify the authoritative repository, repository type, owning organization, lifecycle state, risk tier, deployable units or published outputs, visibility/data classification, and replacement or parent system where applicable.
- **Intent:** Give assessors and consumers the context needed to apply controls correctly and prevent orphaned repositories.
- **Acceptable patterns/equivalents:** Service catalog; repository metadata file; organization inventory; inherited catalog record with repository-level overrides.
- **Evidence/evidence minimum:** Resolvable portfolio entry with all applicable fields and a timestamped owner confirmation. Minimum is one non-conflicting authoritative record.
- **Linked measure:** M-RLP-01 (portfolio classification completeness).
- **Threshold:** Pass at 100%; Concern from 80% to below 100%; Fail below 80% or when authoritative repository, lifecycle, or tier is missing.
- **Unknown/N-A/exception treatment:** N/A is not allowed. Conflicting catalog and repository declarations are Unknown until reconciled.
- **Grade effect:** Scored only in RLP; no standalone grade or assurance override.
- **Minimum assurance:** E2 — Configured; current non-conflicting repository and portfolio records must resolve every required field.
- **Remediation:** Register the repository, classify it with the owner, enumerate outputs/units, and reconcile duplicate metadata.
- **Owner/review date:** Portfolio owner and repository owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004 and SRC-005.

### RLP-02 — Stale branch and ref hygiene

- **Tier/applicability:** Baseline, Elevated, Critical; active repositories using work, release, environment, or maintenance refs.
- **Normative statement:** The repository **MUST** define ref-lifetime and EOL rules consistent with its methodology and **SHOULD** retire stale work refs while preserving required release/history evidence.
- **Intent:** Reduce accidental reuse, hidden divergence, and unprotected abandoned lines without penalizing legitimate long-lived release branches.
- **Acceptable patterns/equivalents:** Automatic deletion after merge; stale-branch review; explicit maintenance-branch EOL; environment ref retained while deployed; immutable release tags retained; retroactive release branch where methodology permits.
- **Evidence/evidence minimum:** Ref inventory; classification; last activity; merge/deployment/support state; declared delivery cadence; owner-approved cadence-relative profile SLO and approval date; deletion/EOL record. Minimum is a disposition and applicable approved SLO for every open non-immutable ref.
- **Linked measure:** M-RLP-02 (stale work-ref rate).
- **Threshold:** Pass at no more than 5%; Concern above 5% through 15%; Fail above 15%. Profile SLOs control which refs are stale.
- **Unknown/N-A/exception treatment:** Immutable tags and supported release/environment refs are excluded, not stale. N/A only when the repository has Main and immutable tags but no other refs. An unclassified ref, missing cadence basis, or unapproved SLO is Unknown; after the owner-approved SLO it is also counted stale, without converting Unknown to known evidence.
- **Grade effect:** Scored only in RLP; the result informs CGD-05 without duplicate points and has no standalone grade cap.
- **Minimum assurance:** E3 — Demonstrated; a complete current ref inventory plus cadence/SLO and event evidence must establish each ref state.
- **Remediation:** Classify refs, merge/close/delete abandoned work, document supported branches and EOL, and automate safe cleanup.
- **Owner/review date:** Maintainer lead; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; profile guidance from SRC-012, SRC-014, SRC-015, SRC-016, and SRC-021.

### RLP-03 — Safe deprecation, archival, and retirement

- **Tier/applicability:** Repositories in deprecated, retired, or archived lifecycle states; active repositories are N/A.
- **Normative statement:** A non-active repository **MUST** state its lifecycle and date, replacement or migration path, last supported release, consumer impact, security/support end date, and preservation policy; write/deploy credentials and unintended automation **MUST** be disabled or removed.
- **Intent:** Make inactivity deliberate and safe rather than indistinguishable from abandonment.
- **Acceptable patterns/equivalents:** Forge archive mode; read-only mirror; tombstone README; retained immutable release evidence; redirected successor repository; documented legal hold.
- **Evidence/evidence minimum:** Archive/deprecation status; notice; successor/migration; consumer inventory or attestation of none; support/EOL; disabled credentials/automation; retention record. Minimum is every applicable retirement assertion.
- **Linked measure:** M-RLP-03 (retirement-control completeness).
- **Threshold:** Pass at 100%; Concern from 80% to below 100% with write/deploy paths already disabled; Fail below 80% or any active production credential/automation without documented purpose.
- **Unknown/N-A/exception treatment:** Active repositories are N/A. Unknown consumers require a documented discovery effort and remain Unknown, not “none.” Legal retention can justify preservation but not active credentials.
- **Grade effect:** Scored only in RLP; archived repositories receive an archival-health result while G-01, G-03, and G-04 remain applicable under their archive-specific contracts. G-02 follows current-output applicability; gate evaluation adds no RLP points.
- **Minimum assurance:** E3 — Demonstrated; current repository, identity, automation, and retention evidence must establish every applicable retirement assertion.
- **Remediation:** Publish the status and migration path, inventory consumers, revoke credentials, disable jobs/webhooks, protect retained evidence, and archive the repository.
- **Owner/review date:** Portfolio owner and former service/product owner; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-004, SRC-006, and SRC-018.

### RLP-04 — Authoritative repository uniqueness

- **Tier/applicability:** Baseline, Elevated, Critical; all portfolio-managed repositories.
- **Normative statement:** Each codebase or deployable unit **MUST** have one declared authoritative repository, and mirrors, forks, templates, generated copies, and successors **MUST** be labeled so they cannot be mistaken for an independent production source.
- **Intent:** Prevent conflicting sources of truth and accidental deployment from a stale copy.
- **Acceptable patterns/equivalents:** Canonical repository URI; read-only mirror metadata; fork relationship; template marker; generated-source header; successor redirect; multi-repo component registry.
- **Evidence/evidence minimum:** Portfolio/codebase inventory; exactly one authoritative URI per unit; required relationship fields for every discovered copy; deployment-source configuration; conflict check. Minimum is complete authority, relationship, and production-source evidence per unit.
- **Linked measure:** M-RLP-04 (authoritative-source uniqueness).
- **Threshold:** Pass when authority uniqueness and production-source assertions pass and relationship-field coverage is 100%; Concern when both critical assertions pass and relationship-field coverage is at least 80% but below 100%; Fail when relationship coverage is below 80%, an active authoritative claim conflicts, or production can source an undeclared copy.
- **Unknown/N-A/exception treatment:** N/A is not allowed. An incomplete portfolio search is Unknown. Distributed forking workflows still require a declared canonical integration repository.
- **Grade effect:** Scored only in RLP; a conflicting production source may inform SPI-02 or SPI-04, which are evaluated under their own controls without duplicating this control's points.
- **Minimum assurance:** E3 — Demonstrated; current portfolio discovery and production-source configuration must establish authority and every copy relationship.
- **Remediation:** Select and register the canonical source, label or archive copies, restrict deployment origins, and document multi-repo relationships.
- **Owner/review date:** Portfolio owner and repository administrator; standard review by 2027-02-09.
- **Authoritative source:** SRC-001; supported by SRC-005 and SRC-017.

## 11. Control coverage summary

| Dimension | Controls | Foundational gates |
|---|---:|---|
| SPI — Source-to-production integrity | 4 | G-01, G-02 |
| BTC — Build, test, and CI health | 5 | — |
| CGD — Change governance and branch discipline | 6 | G-03, G-04 |
| SSC — Security and software-supply-chain health | 4 | — |
| OWM — Ownership and maintainability | 4 | — |
| DCR — Documentation and contributor readiness | 4 | — |
| RRO — Release, rollback, and operational readiness | 4 | — |
| RLP — Repository lifecycle and portfolio hygiene | 4 | — |
| **Total** | **35** | **4** |

The 0.1.0-draft thresholds are calibration defaults. Pilot findings may change a threshold only through a versioned standards decision; assessments must record the catalog version used.
