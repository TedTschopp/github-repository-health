# Repository Classification Guide

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | Provisional; documentation-only |
| Date | 2026-08-09 |
| Intended use | Trial classification before a health assessment |

This guide classifies repository context without prescribing or rewarding a particular Git workflow. Classification determines which outcomes and measures are applicable; it is not itself a health score. Use it before applying the [Repository Health Standard](repository-health-standard.md), [control catalog](control-catalog.md), or [measurement dictionary](measurement-dictionary.md).

Terms are defined in the [glossary](glossary.md). The profile sources linked below are informative. This controlled supporting guide applies the taxonomy and outcomes in the [normative assessment set](repository-health-standard.md#normative-document-set-and-precedence); that set governs if a conflict could change an assessment result.

## 1. Required classification record

Create one classification record for each repository assessment. It MUST contain:

| Field | Required content |
| --- | --- |
| Repository identity | Canonical remote, owner or organization, repository name, and assessment date. |
| Scope | Included and excluded refs, paths, units, release targets, and evidence systems. |
| Main | The ref performing the canonical Main role, written as `Main (<actual-ref>)`; record the default branch separately if different. |
| Production-critical refs | Main plus any release, maintenance, environment, tag, or GitOps refs capable of determining a production or published state. |
| Deployable units | Every independently deployed or published unit, including unit boundary, owner, target, and source-to-release mapping. |
| Repository type | One primary type, zero or more secondary types, and unit-specific types for a monorepo. |
| Lifecycle state | Active, Stable-supported, Experimental, Mirrored, Archived, Retired, or Unknown, with supporting evidence. |
| Risk | Baseline, Elevated, or Critical, with rationale. |
| Declared methodology | The named or described workflow claimed by repository or organizational documentation, plus evidence location and date. |
| Observed methodology | The profile best supported by configuration and operating history, plus evidence window. |
| Workflow axes | The observed value for each axis in section 4. |
| Classification confidence | High, Moderate, or Low, with evidence limitations. This is separate from assessment assurance. |
| Contradictions | Alignment status, unresolved conflicts, and owner explanation where available. |

If evidence is insufficient, record `Unknown` or `Unclassified` with Low confidence. Do not use `Custom/hybrid` as a substitute for missing evidence.

## 2. Repository type classification

Classify a repository by the outcome it is expected to support and the consequence of its use, not by its predominant file extension. A README containing a small amount of code can still be a deployable application; a large source tree can be a template or an inactive mirror.

### 2.1 Canonical types

| Repository type | Use when the repository's supported purpose is… | Classification notes |
| --- | --- | --- |
| **Deployable application** | Producing or configuring an executable service, application, job, function, client, or site that is operated in a runtime environment. | Record each independently deployed component as a deployable unit. A static site can be an application when runtime delivery and operations are the primary contract, or documentation/content when publication is the primary contract. |
| **Library/package** | Publishing reusable code, binaries, modules, plugins, containers, or other artifacts for consumers to incorporate. | The package registry, supported version lines, compatibility contract, and consumer population inform risk and release measures. |
| **Monorepo** | Governing multiple material units with independent build, ownership, release, or deployment boundaries in one Git repository. | Monorepo is an organizational type. Every unit MUST also receive its functional type; one aggregate build or release label cannot replace unit-level classification. |
| **Infrastructure-as-code/GitOps** | Defining infrastructure, platform, policy, deployment, or environment desired state through versioned configuration. | Record whether Git is only a change source or is the reconciled source of truth. Identify every environment and ref or path with promotion authority. |
| **Data/analytics/model** | Producing data pipelines, transformations, queries, dashboards, datasets, notebooks, features, evaluations, or model artifacts. | Record external data, model, parameter, and execution dependencies needed for lineage and reproducibility. |
| **Documentation/content** | Authoring and publishing human-consumable documentation, policy, learning material, editorial content, or a content-driven site. | Rendering, structural validation, link checks, metadata, and publication lineage can constitute buildability. |
| **Template/scaffold** | Generating or seeding other repositories, projects, configurations, or artifacts. | Classify the representative generated result and state the supported generator/template contract. |
| **Sandbox/experimental** | Supporting time-bounded exploration without a production or supported-consumer commitment. | “Experimental” MUST be visible to potential consumers. Any actual production or supported dependency triggers reclassification; this label cannot be used to evade applicable controls. |
| **Mirror/fork** | Replicating an upstream repository, carrying a downstream patch set, or providing a contribution fork rather than acting as the original source. | Record upstream identity, sync direction, divergence policy, and whether the fork publishes an independent derivative. A derivative with its own users also receives the relevant functional type. |
| **Archived/retired** | Preserving history after active change, support, release, or operation has intentionally ended. | Preserve the former functional type and last known release in metadata. Archive status requires evidence of intentional disposition; unexplained inactivity is not enough. |

### 2.2 Mixed repositories

Choose the primary type that best represents the repository-wide operating contract. Record a secondary type when it introduces material controls or release obligations. Examples include:

- a library with a documentation site: primary `Library/package`, secondary `Documentation/content`;
- a GitOps repository that also builds a controller: primary `Monorepo`, with `Infrastructure-as-code/GitOps` and `Deployable application` units;
- an upstream fork that ships an independently supported product: functional product type as primary, `Mirror/fork` as secondary;
- a retired application: primary `Archived/retired`, former type `Deployable application` retained in lifecycle metadata.

Do not create multiple types merely because a repository contains test fixtures, examples, CI configuration, or incidental documentation.

## 3. Classification procedure

Perform these steps in order and retain the evidence used:

1. **Resolve the assessment object.** Confirm the canonical remote, repository ownership, default branch, available refs, and any relationship to an upstream, mirror, or generated repository.
2. **Resolve Main.** Identify the one ref intended to hold the integrated, releasable line and production lineage. The default branch is a candidate, not proof. If no ref performs the Main contract, record that contradiction; do not invent one for scoring convenience.
3. **Inventory units and targets.** Trace release manifests, registries, deployment records, publication systems, GitOps reconcilers, and documented consumers to enumerate deployable or publishable units.
4. **Assign type and lifecycle.** Apply section 2 to the repository and each monorepo unit. Check that “sandbox,” “mirror,” and “archive” claims match actual use.
5. **Collect the declared workflow.** Read repository and organization policy, contribution and release instructions, architecture decisions, and an accountable owner's statement. Record source and revision or date.
6. **Observe the workflow.** Inspect configuration and operating evidence across the axes in section 4. The evidence window SHOULD include at least one representative change-to-release or change-to-publication cycle, not merely a fixed number of days.
7. **Assign methodology profile.** Choose the most explanatory observed profile in section 5. Preserve the declared profile separately, even when it differs.
8. **Assign risk tier.** Apply the impact criteria in the [standard](repository-health-standard.md#4-risk-tiers) to each material unit, then take the highest unit tier as the repository-wide minimum for shared controls.
9. **Rate confidence and contradictions.** Apply section 6 and record access limitations, sparse evidence, and owner explanations.
10. **Review with the owner.** The assessor and accountable owner SHOULD confirm factual scope, type, Main, units, risk, and workflow description before scoring. Disagreement remains visible rather than being silently reconciled.

## 4. Workflow axes

Named methodologies often overlap. These axes are the durable classification record and MUST be completed even when a familiar profile name appears obvious.

| Axis | Values to describe | Useful evidence |
| --- | --- | --- |
| **Canonical integration topology** | One Main line; Main plus `develop`; multiple environment lines; multiple supported version lines; hierarchical integrators. | Commit graph, merge bases, default-branch settings, contribution docs. |
| **Change ingress** | Direct push; gated direct submission; branch pull/merge request; fork pull/merge request; bot or integration-manager submission. | Branch rules, repository permissions, pull/merge request history, audit log. |
| **Branch purpose and lifetime** | No routine branches; short-lived topic branches; release stabilization branches; long-lived environment or maintenance branches. | Active and deleted refs, branch age distribution, merge history, naming/purpose documentation. |
| **Integration cadence** | Continuous/frequent integration; batch or train integration; release-driven integration; irregular/manual integration. | Merge and commit history interpreted against the repository's normal delivery cadence. |
| **Release source** | Main revision/tag; release or maintenance branch; environment branch; generated artifact; GitOps ref/path. | Release manifests, build runs, tags, deployment and registry metadata. |
| **Promotion mechanism** | Promote one immutable artifact; rebuild; merge; cherry-pick/backport; change a desired-state ref/path; automatic reconciliation. | Pipeline definitions and runs, artifact digests, deployment records, reconciler state. |
| **Parallel support** | Current line only; temporary stabilization; multiple supported versions; multiple release trains. | Support policy, version branches, release schedules, backport records. |
| **Control placement** | Pre-submit; pre-merge; post-merge; pre-release; environment approval; reconciler/policy admission. | Required checks, rulesets, review configuration, approvals, bypass and deployment logs. |
| **Repository topology** | Shared canonical repository; contributor forks; downstream fork; mirror; several coordinated repositories. | Remotes, fork network, integration policy, sync automation, upstream metadata. |

Do not classify branch lifetime from names alone. “Short-lived” means that branches are routinely integrated or discarded within the team's intended feedback and release cadence; the assessment records the observed distribution and declared expectation rather than imposing a universal day count.

## 5. Methodology profiles

The observed profile is the closest explanatory model, not a claim that every historical change followed it perfectly.

| Methodology profile | Distinguishing observed pattern | Important boundaries |
| --- | --- | --- |
| **Trunk-based** | Contributors integrate frequently into one Main line, directly or through short-lived branches. Longer work is kept releasable through techniques such as incremental change, feature controls, or abstraction; release branches, if used, are temporary. | A pull request does not make the workflow non-trunk-based. Prefer the more specific `Direct gated trunk` profile when direct submission and pre-submit gating define the workflow. See [Trunk Based Development](https://trunkbaseddevelopment.com/). |
| **GitHub Flow/short-lived feature branches** | Routine changes use a short-lived branch, review through a pull request or equivalent, merge to a deployable Main, and delete or abandon the topic branch after integration. | Hosting on GitHub is not required, and merely using pull requests is not enough. Release behavior and branch lifetime must agree. See [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow). |
| **GitFlow** | A long-lived development integration branch feeds release branches; Main records production releases; feature, release, and hotfix branches have distinct merge paths, with production fixes returned to the development line. | Do not label any use of `develop` as GitFlow. The original model's author now recommends simpler flows for continuous delivery, so fit is contextual rather than a quality signal. See the [original GitFlow model and reflection](https://nvie.com/posts/a-successful-git-branching-model/). |
| **Environment-branch flow** | Long-lived refs represent deployment environments or promotion stages, and changes move between them through merges, cherry-picks, or equivalent controlled promotion. | Environment names alone are not proof; verify that refs actually determine environment content. Main remains the canonical lineage role under this standard. See the environment-branch discussion in [GitLab Flow](https://docs.gitlab.com/topics/gitlab_flow/). |
| **Release train/multi-version maintenance** | Main holds current development while release trains or supported-version branches stabilize and receive selected fixes or backports in parallel. Releases and support policy determine branch lifecycle. | This is not automatically GitFlow: a separate `develop` line and GitFlow merge topology may be absent. Verify that production-only fixes are reconciled with Main. |
| **GitOps promotion** | Versioned declarative desired state determines environments; a software agent pulls it and continuously reconciles actual state. Promotion changes a controlled ref, path, or artifact reference. | A repository containing YAML or infrastructure code is not necessarily GitOps. Automatic pull and reconciliation distinguish the profile. See the [OpenGitOps principles](https://opengitops.dev/). |
| **Fork/integration-manager** | Contributors publish changes in forks or separate repositories; maintainers or a hierarchy of integrators review and merge selected work into the canonical repository. | Record which repository and ref are canonical and how contributor-fork evidence reaches it. See [Pro Git: Distributed Workflows](https://git-scm.com/book/en/v2/Distributed-Git-Distributed-Workflows). |
| **Direct gated trunk** | Routine changes are submitted directly to Main or a staging representation of Main, while pre-submit checks, review, a merge queue, or server-side admission prevents an unvalidated update. Routine feature branches are not the organizing mechanism. | Direct-to-Main without effective gates is not “gated.” Platform rules are examples, not requirements; see GitHub's [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) and [rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets). |
| **Custom/hybrid** | Two or more profiles intentionally govern different axes or units, or the documented design does not fit a named profile. | This is a valid design, not a lower-quality category. It MUST be decomposed by axis and unit and MUST NOT be used to hide uncertainty or contradiction. |

### 5.1 Overlapping profiles

Record one primary observed profile and any material secondary profile. For example, a GitHub Flow change-ingress pattern plus GitOps promotion is normally recorded as `Custom/hybrid`, with both component profiles and their axes named. A monorepo MAY have one repository-wide ingress profile and different unit-specific release profiles.

When `Trunk-based`, `GitHub Flow/short-lived feature branches`, and `Direct gated trunk` all appear plausible, choose based on the workflow's defining mechanism:

- choose `Direct gated trunk` when direct submission with pre-integration gates is primary;
- choose `GitHub Flow/short-lived feature branches` when branch-and-review lifecycle is primary;
- choose `Trunk-based` when frequent single-line integration is the declared and observed organizing principle and neither more specific profile explains it better.

## 6. Declared, configured, and observed workflow

### 6.1 Keep declarations separate

The classification MUST report both the declared and observed methodology. Evidence should be grouped using the assurance model:

- **Declared (E1):** repository or organizational policy, `README`, contribution guide, release guide, architecture decision, or accountable-owner statement.
- **Configured (E2):** branch rules, permissions, CI triggers, release configuration, environment mappings, and GitOps reconciler configuration.
- **Demonstrated (E3):** commit and merge history, pull/merge requests, build and release runs, deployment records, backports, bypasses, and reconciliation events showing the path in use.
- **Sustained effectiveness (E4):** repeated demonstrated operation plus outcome evidence showing that the controls achieve their purpose over the relevant period.

Documentation is not downgraded because it is declarative; it is simply not proof that the workflow operated as stated. Conversely, a commit graph without ownership or intent may show mechanics but not explain purpose.

### 6.2 Observation window

The observation window MUST be recorded with start and end dates. It SHOULD include a representative normal change and a complete release, publication, or promotion cycle. For multi-version maintenance it SHOULD include a backport or maintenance cycle when one occurred. Sampling limitations, missing audit access, migrations, incidents, and exceptional freezes MUST be noted.

A fixed recent window MUST NOT erase relevant evidence when the repository's normal cadence is longer. Use section 7 for stable low-activity repositories.

### 6.3 Classification confidence

Classification confidence describes how reliably the type and workflow profile were identified. It is distinct from the overall assurance rating defined by the [scoring guide](scoring-assurance-exceptions.md).

| Confidence | Criteria |
| --- | --- |
| **High** | Scope and units are complete; material axes have configured and demonstrated evidence; at least one representative operating cycle is visible or an appropriate stable-repository substitute is available; declared and observed behavior align or differences are fully explained. |
| **Moderate** | Multiple independent sources support the profile, but part of a normal cycle, one evidence system, or a material axis is unavailable; any contradiction does not change the best-fit profile. |
| **Low** | Classification relies mainly on declaration, sparse history, names, or owner recollection; material access is missing; competing profiles remain plausible; or unresolved contradictions could change the result. |

An uncommon workflow can receive High confidence. A familiar workflow does not receive High confidence merely because its branch names match a pattern.

### 6.4 Contradictions

Record alignment as one of:

- **Aligned:** declared, configured, and demonstrated behavior materially agree.
- **Explained variation:** a bounded, intentional variance is documented, such as an emergency path, migration, or unit-specific release flow.
- **Unresolved contradiction:** evidence conflicts and no adequate explanation or control exists.
- **Not assessable:** necessary evidence is inaccessible or absent.

Examples of material contradictions include a claimed Main ref that does not contain current production lineage, documented required reviews that can routinely be bypassed without audit, a claimed GitOps flow with no reconciler, and a declared stable repository with active unsupported consumers.

Observed behavior determines the observed profile; the declared label is never overwritten. An unresolved contradiction MAY affect documentation, governance, or gate results, but no points are deducted merely because the observed profile differs by name.

## 7. Stable low-activity repositories

Low commit, release, or contributor counts can indicate maturity, abandonment, retirement, or simply a long support cadence. Activity volume alone MUST NOT determine health.

Use this procedure:

1. Determine whether the repository is **stable-supported**, **archived/retired**, **experimental**, or **unknown** using owner commitment, consumer and production evidence, support policy, disposition metadata, and current risk obligations.
2. Extend historical review to the last representative change and release cycle, while evaluating current ownership, access controls, vulnerability exposure, deployment lineage, and restore obligations as of the assessment date.
3. Record event-rate measures with no qualifying events as `No events observed` or not applicable according to the measurement definition; do not convert absence into a perfect or failing rate.
4. Treat a CI system with no recent run as not recently demonstrated, not as a failed run. Existing configured evidence can support E2; E3 or E4 requires appropriate demonstration or an approved stable-state substitute defined by the control.
5. Do not require archived/retired repositories to maintain current build dependencies unless their retention, restoration, or legal contract requires it. Continue to assess lifecycle metadata, preservation, ownership, and protection of critical refs.

`Stable-supported` requires an identifiable owner and support intent. If those cannot be established, classify lifecycle as `Unknown` rather than assuming stability or abandonment.

## 8. Custom and hybrid workflows

Use `Custom/hybrid` only when the behavior is understood. The classification MUST:

- name each component profile or custom mechanism;
- map every workflow axis to the responsible mechanism;
- identify whether the variation is repository-wide, path-specific, or unit-specific;
- explain how Main remains canonical and how production lineage returns to it;
- identify production-critical refs and their protections;
- state how emergency, backport, and cross-environment changes are reconciled; and
- apply confidence and contradiction rules exactly as for named profiles.

Custom/hybrid is not an exception and does not require remediation merely because it is custom. Health is determined by the standard's outcomes and evidence.

`Upstream-sync`, `read-only`, and `historical workflow` describe axes or context; they are not additional methodology-profile labels. For a mirror, record the sync and write model on the workflow axes, then choose the supported canonical profile that best explains current behavior, use `Custom/hybrid` when the behavior is understood but does not fit another profile, or use `Unclassified` with Low confidence when evidence is insufficient. For an archived/retired repository, retain its last supported canonical profile as historical context, but do not present that historical label as the repository's current observed workflow.

## 9. Risk classification checks

Review at least these impact factors before assigning Baseline, Elevated, or Critical:

- production and publication exposure;
- number and criticality of users, consumers, and downstream systems;
- safety, mission, financial, customer, legal, and regulatory consequence;
- sensitivity and volume of data;
- infrastructure privilege, secret access, and software-supply-chain reach;
- blast radius and substitutability;
- time and complexity to detect, roll back, restore, or withdraw a bad release.

Use the highest applicable factor, not an average. If evidence supports more than one plausible tier, use the higher tier provisionally and record what owner or risk evidence is needed to resolve it. Methodology, repository age, and team size do not lower risk.

## 10. Classification examples

| Scenario | Classification |
| --- | --- |
| A web service uses topic branches and pull requests into deployable Main; each deployment records an image digest and Main commit. | `Deployable application`; observed `GitHub Flow/short-lived feature branches`; unit is the service. |
| A package keeps `release/2.x` and `release/3.x`, backports selected fixes, and develops the next version on Main. | `Library/package`; observed `Release train/multi-version maintenance`. |
| A repository holds three services and a shared library, all released independently through one pull-request process. | `Monorepo`; three `Deployable application` units and one `Library/package` unit; repository-wide ingress profile plus unit release profiles. |
| A desired-state repository accepts pull requests, updates environment paths, and is continuously reconciled by agents. | `Infrastructure-as-code/GitOps`; observed `Custom/hybrid` composed of `GitHub Flow/short-lived feature branches` and `GitOps promotion`. |
| A repository has had no commits for two years, but an owner supports the published library, current vulnerabilities are reviewed, and the last release remains traceable. | `Library/package`; lifecycle `Stable-supported`; historical workflow retained with an evidence-window note. Low activity is not a negative classification. |
| A read-only upstream mirror has sync automation and no independent release or consumers. | `Mirror/fork`; sync method documented; G-02 may be not applicable with approved rationale. |

## 11. Related documents and sources

- [Repository Health Standard](repository-health-standard.md)
- [Glossary](glossary.md)
- [Assessment guide](assessment-guide.md)
- [Scoring, assurance, and exceptions](scoring-assurance-exceptions.md)
- [Trial-use guide](trial-use-guide.md)
- [Source register](source-register.md)
- [Git glossary](https://git-scm.com/docs/gitglossary)
- [Trunk Based Development](https://trunkbaseddevelopment.com/)
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
- [GitFlow: original model and 2020 reflection](https://nvie.com/posts/a-successful-git-branching-model/)
- [GitLab Flow](https://docs.gitlab.com/topics/gitlab_flow/)
- [OpenGitOps principles](https://opengitops.dev/)
- [Pro Git: Distributed Workflows](https://git-scm.com/book/en/v2/Distributed-Git-Distributed-Workflows)
