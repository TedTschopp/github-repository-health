# Repository Health Standard

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | Provisional; documentation-only |
| Date | 2026-08-09 |
| Intended use | Trial assessments and review |

This document defines the normative, outcome-based standard for repository health. It is deliberately independent of Git hosting platform, programming language, delivery tool, and branching methodology. Detailed controls, measures, scoring, and pilot procedures are maintained in the [control catalog](control-catalog.md), [measurement dictionary](measurement-dictionary.md), [scoring, assurance, and exceptions guide](scoring-assurance-exceptions.md), and [governance and pilot guide](governance-and-pilot.md).

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as described by [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) when, and only when, they appear in uppercase.

### Normative document set and precedence

The normative assessment set consists of this standard, the [control catalog](control-catalog.md), and the [scoring, assurance, and exceptions guide](scoring-assurance-exceptions.md). This standard governs scope, canonical taxonomy, the Main and production contract, risk tiers, health domains, and foundational-gate meaning. The control catalog governs control-specific applicability, requirements, evidence minima, freshness, thresholds, measurement mappings, control-specific grade effects, and remediation outcomes when consistent with this standard. The scoring guide governs conformance states, evidence levels, weighting, grade and assurance calculations, N/A and equivalence decisions, exceptions, caps, and result disposition. The [measurement dictionary](measurement-dictionary.md) is the controlled calculation specification subordinate to the normative set; other guides, schemas, templates, examples, and the workbook are supporting artifacts.

If documents conflict, apply the governing document named above. An unresolved conflict that could change applicability, a gate, a rating, assurance, or a score MUST block issuance, be recorded as a standards defect, and be resolved through the [governance process](governance-and-pilot.md); an assessor MUST NOT select the more favorable interpretation.

## 1. Purpose and principles

This standard establishes a common answer to three questions:

1. What kind of repository is this, and how does work flow through it?
2. Does its canonical source remain usable, controlled, and connected to what is running or published?
3. What evidence supports the resulting health assessment?

The standard rests on these principles:

- **Main is the canonical role.** Every in-scope repository MUST identify one branch or equivalent ref that performs the **Main** role, even when its literal name is not `main`.
- **Main is buildable for the repository's type.** “Buildable” includes the appropriate validation outcome for code, infrastructure, data, content, templates, mirrors, and retired repositories; it does not mean that every repository compiles a binary.
- **Production is traceable per deployable unit.** Every running or published unit MUST be traceable to an immutable source revision reachable from Main.
- **Health is outcome-based.** A control may be implemented with any tool or workflow that produces equivalent, inspectable evidence.
- **Methodology is context, not a grade.** Trunk-based development, GitFlow, GitOps, direct-trunk, fork-based, and other intentional approaches are not inherently healthy or unhealthy.
- **Rigor follows risk.** The required strength, independence, and recency of evidence increase from Baseline to Elevated to Critical risk.
- **Unknown is not healthy.** Missing evidence MUST be reported as unknown rather than inferred as passing. Conversely, low activity alone MUST NOT be treated as failure.

Terms used by this standard are defined in the [glossary](glossary.md). Repository type and workflow methodology are determined using the [classification guide](classification-guide.md).

## 2. Scope and non-scope

### 2.1 In scope

This standard applies to Git repositories used to create, configure, publish, operate, preserve, or distribute an organizational asset. It supports all repository types listed in the classification guide, including active, experimental, mirrored, and retired repositories.

An assessment MUST declare:

- the repository and canonical remote being assessed;
- the Main ref and any production-critical refs;
- the repository type, methodology profile, lifecycle state, and risk tier;
- every active deployable or publishable unit in scope;
- the assessment date, evidence window, evidence access limitations, and exclusions.

Where one repository contains multiple independently released or deployed units, conformance MUST be evaluated for each applicable unit as well as for repository-wide controls. A repository-wide green result MUST NOT conceal a failed or unknown foundational gate for one unit.

### 2.2 Out of scope

This standard does not:

- prescribe a branch naming convention, branching methodology, hosting platform, CI/CD product, language, or repository layout;
- require continuous deployment or require Main `HEAD` to be the revision currently in production;
- assess whether the product is commercially valuable, the application code is defect-free, or an individual or team is productive;
- replace security, privacy, records-management, safety, accessibility, or regulatory obligations;
- guarantee that a repository, build, artifact, or production system is secure or reliable;
- require active repositories and intentionally archived repositories to exhibit the same activity pattern;
- make a scanner, dashboard, hosting platform, policy engine, or remediation mechanism part of the normative requirements.

Supporting tools MAY collect evidence and apply the versioned documents, but they do not become normative, cure missing evidence, authorize remediation, or establish compliance. This provisional 0.1.0-draft remains a documentation-defined standard for trial use. It becomes enforceable only through an organization's separately approved governance process.

## 3. The Main contract

### 3.1 Canonical role

**Main** is the repository's canonical, integrated line of record. A repository MUST document which ref performs this role. If the ref is named something else, assessment reports MUST use the form `Main (<actual-ref>)`.

For an active repository:

- Main `HEAD` MUST satisfy the type-specific buildability outcome in section 3.3 and MUST be releasable without first integrating unreconciled production-only source changes.
- Main MUST contain, or have in its history, the immutable source revision for every current production deployment or published release in scope.
- Main MAY be ahead of production. “Represents production” means that production has provable lineage to Main; it does not mean that every Main commit is deployed or that Main `HEAD` and production are identical.
- Release, maintenance, environment, or promotion branches MAY exist. Production fixes made through another ref MUST be reconciled into Main, or an approved time-bounded exception MUST explain why equivalent lineage is preserved.
- The default branch SHOULD be Main. If it is not, the distinction and the controls preventing accidental use of the default branch MUST be documented.

A mutable branch name, environment label, version string, or “latest” tag is not sufficient traceability by itself. Git's definitions of refs, commits, and reachability are grounded in the [Git glossary](https://git-scm.com/docs/gitglossary).

### 3.2 Deployable and publishable units

The assessment MUST inventory each independently deployed or published unit and record its:

- name and accountable owner;
- repository type and risk tier when these differ within the repository;
- type-specific build or validation path;
- production, distribution, or publication target;
- immutable source revision and release or artifact identity;
- deployment or publication evidence;
- rollback, restore, withdrawal, or supersession path, as applicable.

In a monorepo, “the repository was deployed” is not precise enough. Traceability MUST identify the unit, its source boundary, and its unit-specific revision or content identity. If a single commit builds several units, each unit MAY point to the same commit but MUST retain its own release and deployment record.

### 3.3 Type-specific buildability

G-01 uses the following minimum interpretation of “buildable, validated, and releasable for type.” Risk-tier controls can require stronger evidence.

| Repository type | Required Main outcome |
| --- | --- |
| Deployable application | From documented inputs, Main can produce or materialize the deployable application and complete the tests and checks required to release it. Interpreted, low-code, and configuration-driven applications satisfy the same outcome without needing a compilation step. |
| Library/package | Main can produce a consumer-ready package or distribution and complete applicable API, compatibility, and package-integrity checks. |
| Monorepo | The repository can identify affected units and validate their dependency graph. Every changed unit satisfies its own type-specific outcome; an aggregate status MUST NOT mask an unvalidated unit. |
| Infrastructure-as-code/GitOps | Main parses and validates, satisfies applicable policy checks, and can produce an inspectable plan, desired-state change, or reconciliation input without unaccounted production-only configuration. |
| Data/analytics/model | Main can validate or reproduce the relevant pipeline, query, dataset, dashboard, or model artifact with code, data, parameters, and model lineage accounted for to the degree required by risk. |
| Documentation/content | Main can render or otherwise validate the publishable content, structure, links, and required metadata. A repository with no rendering step MUST still run or document its applicable content checks. |
| Template/scaffold | Main can instantiate at least one representative supported result and validate the generated output under the declared support contract. |
| Sandbox/experimental | Main satisfies the explicitly declared minimum validation contract and is clearly prevented from being mistaken for a supported production asset. Production use triggers reclassification and the corresponding stronger requirements. |
| Mirror/fork | Main can be synchronized or compared with its declared upstream and its integrity and divergence can be explained. An independently released derivative also MUST satisfy the outcome for its product type. |
| Archived/retired | Main preserves readable history, disposition metadata, last known release or operating state, and any required restoration material. Current dependency compatibility is not required unless the retention or restoration contract says otherwise. |

Repository type MUST be assigned by intended outcome and operational use, not merely by predominant file extension. See the [classification guide](classification-guide.md#2-repository-type-classification).

### 3.4 Production and release traceability

For each active deployable or publishable unit, an assessor MUST be able to begin with the running or published identity and determine:

1. the environment, channel, registry, site, or other target;
2. the immutable artifact digest, release identifier, content digest, or equivalent identity;
3. the build, publication, or promotion event, when one exists;
4. the immutable Git source revision used;
5. whether that revision is reachable from Main; and
6. the approvals and automated checks that authorized that state, at the rigor required by risk tier.

Traceability MAY be supplied by deployment metadata, an artifact attestation, a release manifest, a signed tag, a GitOps reconciliation record, or equivalent evidence. It MUST NOT depend solely on a mutable label or a person's recollection. [SLSA provenance](https://slsa.dev/spec/v1.2/provenance) is an authoritative model for verifiable artifact-to-source information, but SLSA tooling is not mandatory under this standard.

If artifacts are rebuilt between environments, each environment's artifact MUST retain its own source and build identity. If a unit has no production, publication, distribution, or supported consumer, G-02 MAY be marked not applicable only with a recorded rationale and approval under the exception rules.

## 4. Risk tiers

Risk tier describes consequence and assurance need, not repository importance or team performance. The highest applicable unit risk establishes the repository-wide minimum for shared controls; unit-specific controls MAY be assessed at their own higher tier.

| Tier | Typical context | Expected control strength |
| --- | --- | --- |
| **Baseline** | Limited blast radius; no material safety, regulatory, privileged-access, or sensitive-data consequence; straightforward recovery. | Identified ownership, repeatable validation, auditable changes, protected production-critical refs, and inspectable release evidence. Manual evidence MAY be acceptable when it is reliable and current. |
| **Elevated** | Production service, broadly consumed package, shared platform, confidential data, material financial or operational impact, or difficult recovery. | Required and independently reviewable checks, stronger access separation, automated traceability where practicable, active vulnerability and dependency management, and a tested recovery or rollback approach. |
| **Critical** | Safety- or mission-critical operation, privileged infrastructure or security control, regulated high-impact data, very broad blast radius, or severe recovery constraint. | Strong separation of duties, tamper-resistant audit evidence, tightly controlled build and release identities, independently verifiable provenance appropriate to the threat model, exercised recovery, and prompt detection of unauthorized or divergent state. |

Assessors MUST record the reason for a tier. A repository MUST NOT be placed in a lower tier merely because stronger evidence is unavailable. Organizational risk policy MAY add deterministic criteria but MUST NOT weaken these outcomes.

## 5. Foundational gates

The following gates establish the minimum credible foundation for an overall health grade.

| Gate | Normative requirement |
| --- | --- |
| **G-01 — Main buildable** | Main MUST be buildable, validated, and releasable according to the repository type and declared support contract. |
| **G-02 — Production traceable** | For every applicable deployable or publishable unit, the production or published artifact MUST be traceable to an immutable source revision reachable from Main. |
| **G-03 — Changes controlled** | Changes reaching Main MUST follow a controlled, auditable path appropriate to the risk tier, including attributable actors, required validation, and recorded bypasses. |
| **G-04 — Critical refs protected** | Main and all other production-critical refs MUST be protected against unauthorized change, deletion, and history rewrite through platform controls or demonstrably equivalent controls. |

Gate evidence is evaluated using the evidence levels in the [scoring, assurance, and exceptions guide](scoring-assurance-exceptions.md). An applicable gate that fails or remains at **E0 — Unknown** caps the effective repository result at **D/M1 — Developing**, even when the raw score is higher. The raw score and the reason for the cap MUST remain visible.

Not applicable is not the same as unknown. A gate MAY be marked not applicable only when its triggering outcome truly does not exist, the rationale is documented, and the decision is approved under the assessment rules. G-01, G-03, and G-04 normally apply to every repository, including archived repositories under their type-specific contract. For G-02, each applicable unit is evaluated independently; any failed or unknown unit causes the repository-level gate to fail or remain unknown.

Risk acceptance does not turn a failed gate into a passed gate. It records an accountable decision while the grade cap remains in force.

## 6. Health domains

Detailed controls and measures are maintained separately so that this standard remains stable. Every assessment MUST address all eight domains, using not-applicable decisions only as defined by the scoring guide.

### 6.1 Source-to-production integrity (SPI)

The repository MUST preserve a trustworthy, inspectable path from Main to every active release, artifact, and production or publication target. It MUST make source-only, artifact-only, and environment-only drift detectable and assign responsibility for reconciliation. Provenance strength and recency MUST be proportionate to risk.

### 6.2 Build, test, and CI health (BTC)

The repository MUST define its type-specific validation contract and apply it to changes reaching Main. Required checks MUST be repeatable, their results visible, and failures or unreliable checks resolved or explicitly risk-accepted. Test scope, isolation, and reproducibility SHOULD reflect the consequence of failure rather than a universal coverage target.

### 6.3 Change governance and branch discipline (CGD)

The Main ref, change path, methodology, roles, and bypass process MUST be declared. Actual changes MUST be attributable and auditable, and controls MUST be strong enough for the risk tier. Temporary, release, maintenance, environment, and fork refs MUST have clear purposes and MUST NOT create unexplained, indefinite divergence from Main.

### 6.4 Security and software-supply-chain health (SSC)

The repository MUST manage source, dependency, credential, workflow, build, and artifact risks proportionately. It MUST define how vulnerabilities and exposed secrets are detected, triaged, and resolved; constrain privileged automation; and preserve sufficient dependency and provenance evidence to investigate a release. [NIST SP 800-218 SSDF](https://csrc.nist.gov/pubs/sp/800/218/final), [SLSA](https://slsa.dev/), and [OpenSSF Scorecard](https://scorecard.dev/) are informative sources, not mandated implementations.

### 6.5 Ownership and maintainability (OWM)

The repository MUST have an accountable owner, a supported contact path, and an understood maintenance commitment. Access, knowledge concentration, dependency stewardship, and material technical debt MUST be managed so that the asset does not depend invisibly on one unavailable person or obsolete process.

### 6.6 Documentation and contributor readiness (DCR)

Documentation MUST accurately state the repository's purpose, type, lifecycle, Main ref, workflow, supported build or validation path, release process, ownership, and contribution expectations. An authorized new maintainer SHOULD be able to locate the information needed to make and validate a routine change without relying on undocumented oral knowledge.

### 6.7 Release, rollback, and operational readiness (RRO)

Active deployable or publishable units MUST have identifiable releases and accountable release decisions. The repository or linked operating record MUST define how to deploy or publish, observe the result, and roll back, roll forward, restore, withdraw, or supersede it. Recovery evidence and exercise frequency MUST be proportionate to risk.

### 6.8 Repository lifecycle and portfolio hygiene (RLP)

The repository MUST declare whether it is active, stable-supported, experimental, mirrored, archived, or retired; identify material upstream, downstream, duplicate, and fork relationships; and apply appropriate retention and disposition controls. Stable low activity MUST be distinguished from abandonment. Archived or retired repositories MUST be clearly marked and protected from accidental release or change.

## 7. Conformance and evidence

Assessment follows the [assessment guide](assessment-guide.md) and records results using the approved templates. For each applicable control, the assessor MUST record:

- conformance as **Unmet**, **Partially met**, or **Met**; “Exemplary” is an annotation and does not add points;
- evidence strength from **E0 — Unknown** through **E4 — Sustained effectiveness**;
- the source, collection date, observation window, and access limitation for the evidence;
- the affected repository or deployable unit; and
- a rationale for every not-applicable decision.

Declared policy is evidence of intent, not proof of operation. Configured controls, demonstrated executions, and evidence of sustained effectiveness provide progressively stronger assurance. The raw score, effective grade, assurance result, gate status, risk tier, and classification confidence MUST be reported separately; they MUST NOT be collapsed into one unexplained number.

Conformance MUST be judged against outcomes applicable to the repository's type, risk, lifecycle, and declared support contract. Assessors MUST NOT award or deduct points merely for choosing a named branching methodology. Sparse activity MUST be handled using the stable low-activity procedure in the [classification guide](classification-guide.md#7-stable-low-activity-repositories).

## 8. Exceptions and conflicts

An exception MUST identify the requirement, affected units, business rationale, risk owner, compensating controls, approval, review date, and expiration or exit condition. It MUST remain visible in the assessment. An expired or unevidenced exception has no effect.

Where this standard conflicts with a stronger legal, regulatory, safety, security, records, or organizational requirement, the stronger requirement governs and the conflict MUST be recorded. Where local policy is weaker, this standard's outcome remains unmet unless governance explicitly changes the applicable standard; an exception alone does not rewrite it.

## 9. Related documents and sources

- [Classification guide](classification-guide.md)
- [Glossary](glossary.md)
- [Control catalog](control-catalog.md)
- [Measurement dictionary](measurement-dictionary.md)
- [Scoring, assurance, and exceptions](scoring-assurance-exceptions.md)
- [Governance and pilot guide](governance-and-pilot.md)
- [Source register](source-register.md)
- [Git glossary](https://git-scm.com/docs/gitglossary)
- [NIST Secure Software Development Framework, SP 800-218](https://csrc.nist.gov/pubs/sp/800/218/final)
- [SLSA specification](https://slsa.dev/spec/v1.2/)
- [OpenGitOps principles](https://opengitops.dev/)
- [OpenSSF Scorecard](https://scorecard.dev/)
