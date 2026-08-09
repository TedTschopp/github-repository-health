# Repository Health Glossary

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | Provisional; documentation-only |
| Date | 2026-08-09 |

This controlled glossary standardizes terminology for the provisional [Repository Health Standard](repository-health-standard.md) and its supporting documents. Where a local definition differs from everyday usage, use the definition here unless it conflicts with the [normative assessment set and precedence](repository-health-standard.md#normative-document-set-and-precedence). Git's own object and ref terminology follows the [Git glossary](https://git-scm.com/docs/gitglossary).

## A

### Accountable owner

The person or organizational role answerable for the repository's support contract, risk decisions, access model, lifecycle, and disposition. A contact list or recent contributor is not automatically the accountable owner.

### Active

A lifecycle state in which supported change, release, deployment, publication, or operational use continues. Activity frequency is contextual; an active repository can change infrequently.

### Archived

A lifecycle state in which active change and release have intentionally ended but history, disposition metadata, last known release evidence, and required restoration material are preserved. Archived repositories remain subject to ownership, retention, and ref-protection obligations even when current build compatibility is not required.

### Artifact

An output produced, selected, or assembled for distribution, deployment, publication, or consumption. Examples include a binary, package, container image, infrastructure bundle, model, dataset, rendered site, document, or generated project. An artifact SHOULD have an immutable identity such as a digest or a version bound to immutable evidence.

### Assessment

A time-bounded, evidence-backed evaluation of one repository and its in-scope deployable units against the standard. An assessment includes classification, gate decisions, control conformance, evidence strength, measurements, raw score, effective grade, assurance result, exceptions, and findings.

### Assurance

Confidence justified by the strength and coverage of evidence supporting an assessment result. Assurance is reported separately from conformance and grade. See the [scoring, assurance, and exceptions guide](scoring-assurance-exceptions.md).

### Assurance index

The coverage calculation that maps evidence levels E0 through E4 to 0, 25, 50, 75, and 100 respectively, then aggregates them as defined by the scoring guide. **High** assurance is at least 75 with no foundational gate below E3; **Moderate** is at least 50 and below 75; **Low** is below 50. A high health score does not imply High assurance.

## B

### Baseline risk

The lowest of the three risk tiers. It applies where failure has limited blast radius and no material safety, regulatory, privileged-access, sensitive-data, or difficult-recovery consequence. Baseline does not mean “no risk” or exempt a repository from foundational gates.

### Branch

A movable Git ref denoting a line of development. Branch names do not establish branch purpose; purpose is determined from declared and observed use.

### Build

The repeatable process that transforms or validates repository inputs into a releasable outcome. It can compile code, package an interpreted application, validate infrastructure, run a data pipeline, render content, instantiate a template, compare a mirror, or verify an archive. Compilation is only one kind of build.

### Buildable

Capable of completing the documented, type-specific build or validation contract from Main using controlled inputs and a supported process. Buildable does not require every external service to be live during an assessment, but unavailable dependencies, substitutions, and unexecuted steps MUST be visible in the evidence.

### Bypass

An authorized path that avoids, overrides, or defers a normally required control. A valid bypass is attributable, auditable, reasoned, time-bounded where appropriate, and retrospectively reviewed at the rigor required by risk. An undocumented override is not a valid bypass.

## C

### Canonical remote

The repository location recognized as the official source for assessment, collaboration, and release lineage. A local clone, cache, mirror, or contributor fork is not canonical unless governance explicitly designates it.

### Change

Any update that can alter source, build logic, dependencies, policy, configuration, generated output, release metadata, or a production/published state. Bot and administrative updates are changes as well as human-authored commits.

### Classification confidence

The High, Moderate, or Low rating describing how reliably repository type and methodology were identified. It is based on classification evidence and contradictions and is distinct from assessment assurance.

### Conformance

The degree to which an applicable control outcome is satisfied: **Unmet** (0), **Partially met** (50), or **Met** (100). **Exemplary** is an annotation for reusable or notably effective practice and does not add points.

### Control

A required or recommended outcome that reduces repository risk or establishes a health capability. A control states what must be true without prescribing one product or implementation. Controls are defined in the [control catalog](control-catalog.md).

### Critical risk

The highest risk tier, used for safety- or mission-critical functions, privileged infrastructure or security controls, regulated high-impact data, very broad blast radius, or severe recovery constraints. Critical repositories require the strongest independence, tamper resistance, provenance, and recovery evidence.

### Custom/hybrid

A methodology profile used when understood behavior intentionally combines named profiles, varies by workflow axis or deployable unit, or does not fit another profile. It is not a negative classification and MUST NOT be used as a substitute for insufficient evidence.

## D

### Declared workflow

The repository methodology described by current policy, repository documentation, an architecture decision, release instructions, or an accountable owner's statement. It is evidence of intent, normally E1, and is reported separately from the observed workflow.

### Default branch

The ref selected by the hosting service for cloning, browsing, and common operations. It SHOULD perform the Main role, but the two terms are not synonymous. A difference MUST be documented.

### Deployable unit

The smallest independently deployed, promoted, rolled back, restored, or operated component whose production identity and source lineage must be known. A monorepo can contain many deployable units.

### Demonstrated evidence (E3)

Evidence showing that a declared and configured control operated on a representative real event, such as a completed build, reviewed change, release, deployment, restore, or reconciliation. A single demonstration does not by itself establish sustained effectiveness.

### Dimension

One of eight health domains used to group controls and measurements:

1. Source-to-production integrity (SPI)
2. Build, test, and CI health (BTC)
3. Change governance and branch discipline (CGD)
4. Security and software-supply-chain health (SSC)
5. Ownership and maintainability (OWM)
6. Documentation and contributor readiness (DCR)
7. Release, rollback, and operational readiness (RRO)
8. Repository lifecycle and portfolio hygiene (RLP)

### Documentation-only

The status of the normative 0.1.0-draft standard: requirements, evidence rules, and scoring are defined in controlled documents rather than embedded invisibly in a platform. Supporting automation may collect evidence and apply those documents, but it does not become normative, establish compliance, enforce releases, or remediate repositories.

## E

### Sustained effectiveness evidence (E4)

Evidence that a control operates repeatedly and achieves its intended outcome over the relevant risk and observation period. E4 requires outcome or trend evidence beyond configuration and one successful example.

### Effective grade

The reported grade after foundational-gate caps are applied to the raw score. A failed or E0/Unknown applicable gate caps the effective grade at D/M1 — Developing; the raw result remains visible.

### Elevated risk

The middle risk tier, used for production services, broadly consumed packages, shared platforms, confidential data, material operational or financial impact, or difficult recovery that does not meet Critical criteria.

### Environment

A distinct target or operating context such as development, test, staging, production, a customer channel, package registry, publication site, or region. An environment branch is a Git ref intended to determine or promote the state of such a target.

### Evidence

An inspectable record supporting a classification, conformance, gate, measurement, or exception decision. Every cited item SHOULD identify source, time, scope, and access limitation. Evidence can be declarative, configured, demonstrated, or effective; unsupported inference is E0/Unknown.

### Evidence levels

The common evidence-strength scale:

| Level | Name | Meaning |
| --- | --- | --- |
| **E0** | Unknown | No sufficient evidence is available to determine whether the outcome exists or operates. |
| **E1** | Declared | Intent or procedure is documented or attested by an accountable source. |
| **E2** | Configured | A control or process is inspectably configured, but representative operation is not yet shown. |
| **E3** | Demonstrated | Representative operating evidence shows the control worked on a real event. |
| **E4** | Sustained effectiveness | Repeated operation and outcome evidence show the control is achieving its purpose over the relevant period. |

Evidence level does not replace conformance. A well-evidenced failure can be E4 evidence supporting an Unmet control.

### Exception

An approved, visible, time-bounded decision to deviate from a requirement while retaining stated risk, compensating controls, ownership, review date, and exit condition. An exception does not automatically make a control Met or remove a foundational-gate cap.

### Experimental

A lifecycle state for time-bounded exploration without a supported production or consumer commitment. It must be visible to potential consumers. Actual production reliance overrides the label and triggers reclassification.

## F

### Foundational gate

One of four non-negotiable outcomes that bound the credibility of an overall health result:

- **G-01 — Main buildable:** Main is buildable, validated, and releasable for type.
- **G-02 — Production traceable:** each applicable production or published unit traces to an immutable revision reachable from Main.
- **G-03 — Changes controlled:** changes reaching Main use a controlled, auditable path.
- **G-04 — Critical refs protected:** Main and other production-critical refs resist unauthorized change, deletion, and history rewrite.

### Fork

A repository derived from another repository with its own remote identity. It can be a contribution vehicle, maintained downstream derivative, or independent product. Upstream, divergence, integration, and release relationships determine its classification.

## G

### GitOps

An operating model in which desired state is declarative, versioned and immutable, pulled automatically, and continuously reconciled by software agents, consistent with the [OpenGitOps principles](https://opengitops.dev/). Storing infrastructure files in Git without pull-based reconciliation is not sufficient to establish GitOps.

### Grade

The maturity label derived from a 0–100 raw score and then limited by gate rules:

| Grade | Maturity | Raw-score band |
| --- | --- | --- |
| **A / M4** | Leading | 90–100 |
| **B / M3** | Managed | 80–<90 |
| **C / M2** | Defined | 70–<80 |
| **D / M1** | Developing | 60–<70 |
| **F / M0** | At Risk | <60 |

Grade is not assurance, risk tier, or classification confidence. See the [scoring guide](scoring-assurance-exceptions.md).

## H

### Health

The evidenced ability of a repository, in its actual type, lifecycle, methodology, and risk context, to preserve trustworthy source, validate changes, govern contribution, manage supply-chain risk, sustain ownership, enable contributors, release and recover, and maintain appropriate lifecycle hygiene.

### Health domain

Synonym for [dimension](#dimension).

## I

### Immutable revision

A content-addressed Git commit identifier or an equivalently fixed source identity that cannot be silently retargeted. A branch name is mutable. A tag is treated as immutable evidence only when controls prevent or detect unauthorized retargeting.

### Integration

The act of bringing a change into the canonical development line or its controlled pre-integration representation. Integration can occur by merge, rebase, cherry-pick, patch application, submit queue, or another auditable mechanism.

## L

### Lifecycle state

The repository's declared operating condition: **Active**, **Stable-supported**, **Experimental**, **Mirrored**, **Archived**, **Retired**, or **Unknown**. Lifecycle affects applicable evidence and activity interpretation but does not by itself determine health.

### Lineage

The verifiable relationship among source revision, build inputs, artifact or release identity, deployment or publication event, and resulting target state.

## M

### Main

The canonical, integrated Git ref that serves as the repository's releasable line of record and contains the lineage of every current production or published revision in scope. **Main** is a role and is capitalized in these documents; its literal branch name can be `main`, `master`, or another documented value.

Main `HEAD` MAY be ahead of production. Main represents production when each current production or published source revision is immutable, reachable from Main, and connected by release and deployment evidence. An unreconciled production-only change violates the Main contract.

### Main HEAD

The commit currently referenced by Main. It is expected to meet the type-specific validation and releasability contract even when it has not been deployed.

### Measure

A defined observation used to evaluate a control or health domain. A complete measure specifies question, population, formula or decision rule, unit, evidence source, window, frequency, segmentation, target or interpretation, exclusions, and failure handling. Measures are defined in the [measurement dictionary](measurement-dictionary.md).

### Methodology profile

A named explanatory model for how changes integrate and releases or promotions occur. The canonical profiles are Trunk-based; GitHub Flow/short-lived feature branches; GitFlow; Environment-branch flow; Release train/multi-version maintenance; GitOps promotion; Fork/integration-manager; Direct gated trunk; and Custom/hybrid.

### Mirror

A repository replica maintained from an upstream source, often automatically and sometimes read-only. A mirror's sync direction, delay, integrity, ownership, and independent release behavior must be explicit.

### Monorepo

A single Git repository containing multiple material units with independent build, ownership, release, deployment, or support boundaries. A monorepo assessment retains repository-wide controls and unit-level type, risk, traceability, and gate results.

## N

### Not applicable (N/A)

A determination that a control or gate is not triggered by the repository's real type, lifecycle, units, or supported outcomes. N/A requires a rationale and approval and is excluded from scoring as defined by the scoring guide. Lack of evidence, capability, time, or access is not N/A.

## O

### Observation window

The dated period from which operating evidence and measurements are sampled. It should include a representative change-to-release cycle or an appropriate stable-state substitute. Window choice must be recorded and interpreted against normal repository cadence.

### Observed workflow

The methodology profile best supported by configured and demonstrated repository behavior. It is reported separately from the declared workflow and decomposed using the axes in the [classification guide](classification-guide.md#4-workflow-axes).

## P

### Production

The environment, channel, registry, publication target, or operating state relied upon by intended users or downstream systems. A repository can have more than one production target. The assessment must name them; “production” is not assumed to mean only a server runtime.

### Production-critical ref

Any branch, tag, or other Git ref whose unauthorized update, deletion, or history rewrite could change, misrepresent, prevent recovery of, or break lineage to a production or published state. Main is always production-critical for an active production repository; release, maintenance, environment, and GitOps refs may also be critical.

### Protected ref

A production-critical ref governed by controls that prevent or promptly detect unauthorized update, deletion, and history rewrite. Hosting-platform branch protection is one implementation; demonstrably equivalent server-side or governance controls can satisfy the outcome.

### Provenance

Verifiable information describing where, when, and how an artifact was produced and the source and inputs from which it originated, consistent with the [SLSA provenance model](https://slsa.dev/spec/v1.2/provenance). Provenance is stronger than an unverified version label.

### Publication

The act of making content or an artifact available to its intended consumers, including pushing a package, publishing a site or document, registering a model or dataset, or distributing a template.

### Publishable unit

The smallest independently published, versioned, withdrawn, or superseded item whose source lineage must be known. It is treated like a deployable unit for G-02 and scoring.

## R

### Raw score

The numeric 0–100 result calculated from applicable control conformance before a foundational-gate cap. It remains visible even when the effective grade is lower.

### Reachable from Main

A Git commit relationship in which the immutable source revision is Main itself or an ancestor of Main under the assessed repository's commit graph. A commit that exists only on a release, environment, detached, or fork ref is not reachable from Main until it is integrated into Main's history. Equivalent-content patches with different commit identities require explicit reconciliation evidence; they are not assumed reachable.

### Releasable

In a state that has satisfied the repository's declared validation and risk controls and can proceed through the documented release or publication path without first adding unreconciled source changes. Releasable does not mean already approved for a specific deployment window.

### Release

An identified, supportable version or content state intended for deployment, publication, or consumption. A release record binds a unit to immutable source and artifact or content identity; a Git tag alone may be only one part of that record.

### Release train

A coordinated schedule or version line through which a bounded set of changes is stabilized and released. Multiple trains can be supported concurrently and can use maintenance branches distinct from Main.

### Repository type

The supported outcome category used to establish applicability and type-specific buildability: Deployable application; Library/package; Monorepo; Infrastructure-as-code/GitOps; Data/analytics/model; Documentation/content; Template/scaffold; Sandbox/experimental; Mirror/fork; or Archived/retired.

### Restore

Re-establishing a known service, artifact, configuration, repository, data, or content state after loss or corruption. Restore can be required even where rollback is not meaningful.

### Retired

A lifecycle state in which supported use and operation have intentionally ended and disposition obligations have been completed or assigned. See also Archived.

### Risk tier

The Baseline, Elevated, or Critical classification describing consequence and assurance need. Risk tier determines control rigor; it is not a health score.

### Rollback

Returning a target to a previously known release or state. It differs from reverting source and may be impossible for irreversible data changes.

### Roll forward

Recovering by deploying or publishing a new corrective release rather than returning to the prior state. A valid roll-forward strategy includes detection, decision, and time-to-recovery expectations.

## S

### Stable-supported

A lifecycle state for a repository that changes infrequently but has an identified owner, current support intent, known consumers or operating use, and maintained risk obligations. It is not inferred from inactivity alone.

### Source-to-production integrity

The property that production or published state can be traced through immutable artifact, build, release, and deployment evidence to an immutable source revision reachable from Main, with divergence detectable and reconcilable.

### Support contract

The explicit statement of supported users, versions, environments, interfaces, service or maintenance expectations, build or restore obligations, and end-of-life conditions for a repository or unit.

## T

### Traceability

The ability to navigate reliable identifiers and evidence between a target state, release or artifact, producing event, source revision, checks, and approvals. Traceability should work from production back to source, not only from a source commit toward an intended release.

### Type-specific buildability

The interpretation of buildable appropriate to a repository type, as specified by section 3.3 of the [standard](repository-health-standard.md#33-type-specific-buildability). It prevents binary-compilation assumptions from misgrading infrastructure, data, content, templates, mirrors, sandboxes, and archives.

## U

### Unknown

A result used when evidence is insufficient to determine truth. Unknown is E0; it is not the same as Unmet or N/A. An applicable foundational gate at E0 caps the effective grade at D/M1 — Developing.

### Unclassified

A classification result used when evidence is insufficient to select a repository type or methodology profile reliably. It is recorded with Low classification confidence and is distinct from `Custom/hybrid`, which requires understood behavior. `Unknown` may be used for an unresolved classification field; `Unclassified` is the preferred value for an unresolved methodology profile.

### Unmet

A conformance result indicating that the required outcome is absent or materially ineffective. It scores 0 for that control under the provisional scoring model.

## V

### Validation contract

The documented set of checks, inputs, environments, and acceptance outcomes that Main must satisfy to be buildable and releasable for the repository type and risk. It can include compilation, tests, policy checks, rendering, planning, generation, integrity comparison, or archival verification.

## W

### Withdraw

To stop distributing or presenting a published artifact or content item as supported. Withdrawal is the publication analogue of some rollback actions and must preserve audit and lineage evidence where required.

### Workflow axis

One independently observable aspect of methodology: integration topology, change ingress, branch purpose and lifetime, integration cadence, release source, promotion mechanism, parallel support, control placement, or repository topology. Axes make custom and overlapping workflows classifiable without forcing a misleading label.

## Related documents

- [Repository Health Standard](repository-health-standard.md)
- [Repository Classification Guide](classification-guide.md)
- [Control catalog](control-catalog.md)
- [Measurement dictionary](measurement-dictionary.md)
- [Scoring, assurance, and exceptions](scoring-assurance-exceptions.md)
- [Source register](source-register.md)
