# Repository Health Source Register

**Status:** Provisional 0.1.0-draft

**Register version:** RH-SOURCES-0.1

**Common access/verification date:** 2026-08-09

**Next register review:** 2026-11-09

## 1. Source policy

The 0.1.0-draft normative assessment set consists only of the [Repository Health Standard](repository-health-standard.md), [Control Catalog](control-catalog.md), and [Scoring, Assurance, and Exceptions](scoring-assurance-exceptions.md). The Standard governs scope, canonical taxonomy, the Main and production contract, risk tiers, health domains, and foundational-gate meaning. The Catalog governs control-specific applicability, requirements, evidence minima, freshness, thresholds, measurement mappings, control-specific grade effects, and remediation outcomes when consistent with the Standard. The Scoring guide governs conformance states, evidence levels, weighting, grade and assurance calculations, N/A and equivalence decisions, exceptions, caps, and result disposition.

The [Measurement Dictionary](measurement-dictionary.md) is the controlled calculation specification subordinate to that normative set. The [Classification Guide](classification-guide.md) and [Glossary](glossary.md) are controlled supporting specifications that apply taxonomy delegated by the Standard; they do not redefine it. This register is a controlled supporting artifact governing source identity and role. Other guides, schemas, templates, examples, and the workbook are supporting artifacts. A subordinate document must not narrow or contradict a governing normative outcome; a conflict is recorded and resolved under the Standard's precedence rule. External sources provide requirement language, research, platform semantics, methodology definitions, or evidence heuristics as recorded below; they do not silently change 0.1.0-draft.

Roles mean:

- **Normative — policy:** directly governs 0.1.0-draft assessments.
- **Normative — vocabulary/conditional:** binding only for the stated vocabulary or when the repository claims conformance to that external specification.
- **Authoritative platform reference:** primary vendor documentation for how evidence or enforcement works; informative to the health policy.
- **Authoritative methodology reference:** primary originator/vendor description used to classify a declared methodology; informative to the health score.
- **Informative framework/research:** supports rationale, control design, or an outcome panel but is not scored directly.
- **Informative heuristic:** provides useful observable signals, not definitive conformance.

All sources were opened or otherwise verified on 2026-08-09. “Living snapshot” means the publisher exposes no stable document version; the access date pins the reviewed content. A reviewer must record a content hash or archive reference in a future evidence package if exact long-term replay is required.

## 2. Registered sources

| ID | Publisher and source | Pinned version/status | Role in 0.1.0-draft | Used for | Access date | Refresh cadence / next review |
|---|---|---|---|---|---|---|
| **SRC-001** | Repository Health controlled document set: normative [standard](repository-health-standard.md), [control catalog](control-catalog.md), and [scoring/assurance/exceptions](scoring-assurance-exceptions.md); controlled supporting [classification guide](classification-guide.md), [glossary](glossary.md), [measurement dictionary](measurement-dictionary.md), and this register | Provisional 0.1.0-draft / RH-METRICS-0.1 / RH-SOURCES-0.1 | **Normative — policy only for the Standard, Catalog, and Scoring guide.** Classification, glossary, measurement, and source-register materials are controlled supporting specifications subordinate to the normative set, as stated in section 1. | All controls and measures | 2026-08-09 | Semiannual and after pilot calibration; next 2027-02-09 |
| **SRC-002** | IETF, [RFC 2119](https://www.rfc-editor.org/info/rfc2119/) as updated by [RFC 8174](https://www.rfc-editor.org/info/rfc8174/) (BCP 14) | RFC 2119 (March 1997) + RFC 8174 (May 2017), Best Current Practice | **Normative — vocabulary.** Governs uppercase MUST, SHOULD, MAY, and related terms only. | Normative language throughout | 2026-08-09 | Annual and on BCP update; next 2027-08-09 |
| **SRC-003** | NIST, [SP 800-218 Secure Software Development Framework](https://csrc.nist.gov/pubs/sp/800/218/final) and [final PDF](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218.pdf) | Version 1.1, Final, 2022-02-03. SP 800-218 Rev.1 / SSDF 1.2 was still an initial public draft at this register cut and is not adopted. | **Informative framework.** Outcome-oriented secure-development and evidence rationale; no wholesale NIST conformance claim. | SPI, BTC, CGD, SSC, OWM, RRO | 2026-08-09 | Quarterly while 1.2 is in revision, then on final release; next 2026-11-09 |
| **SRC-004** | OpenSSF, [Open Source Project Security Baseline](https://baseline.openssf.org/versions/2026-02-19.html) | **Current v2026.02.19** | **Normative — conditional baseline.** Binding only for a project claiming OSPS conformance; otherwise it supports independently stated Catalog controls without joining the normative assessment set. | Branch protection, MFA/least privilege, CI trust, secrets, documentation, governance, dependency and artifact hygiene | 2026-08-09 | Quarterly and whenever “current” changes; next 2026-11-09 |
| **SRC-005** | SLSA community/Linux Foundation, [SLSA specification](https://slsa.dev/spec/v1.2/), [Source requirements](https://slsa.dev/spec/v1.2/source-requirements), and [provenance](https://slsa.dev/spec/v1.2/provenance) | **Version 1.2, Approved**, announced 2025-11-24; supersedes the planning reference to v1.1 | **Normative — conditional.** Binding for any SLSA level/property claim; otherwise authoritative supply-chain guidance. | Immutable revisions, source controls, two-party review, build/source provenance, traceability | 2026-08-09 | Quarterly and on approved specification release; next 2026-11-09 |
| **SRC-006** | OpenSSF, [Scorecard v5.5.0](https://github.com/ossf/scorecard/releases/tag/v5.5.0) and [v5.5.0 check documentation](https://github.com/ossf/scorecard/blob/v5.5.0/docs/checks.md) | **v5.5.0**, signed release, commit `c395761`, released 2026-04-23 | **Informative heuristic.** Structured checks and risks are measurement inspiration; aggregate Scorecard score is not imported. OpenSSF explicitly says Scorecard is not one-size-fits-all or definitive. | Branch protection, review, CI, dangerous workflows, dependency pinning, binaries, maintenance caveats | 2026-08-09 | Quarterly and on major/minor release; next 2026-11-09 |
| **SRC-007** | DORA/Google Cloud, [Software delivery performance metrics](https://dora.dev/guides/dora-metrics/) and [metrics history](https://dora.dev/insights/dora-metrics-history/) | Living research guide updated **2026-01-05**; five-metric model (history updated 2026-01-02) | **Informative research only.** The five DORA outcomes are a separate panel and never enter the repository-health score. | DORA-CLT, DORA-DF, DORA-FDRT, DORA-CFR, DORA-DRR; anti-gaming/context guidance | 2026-08-09 | Semiannual and after annual DORA research release; next 2027-02-09 |
| **SRC-008** | DORA/Google Cloud, [Version control capability](https://dora.dev/capabilities/version-control/) | Living snapshot accessed 2026-08-09 | **Informative research/guidance.** | Reproducible source, environment/build/deploy assets, rollback capability, traceability | 2026-08-09 | Semiannual; next 2027-02-09 |
| **SRC-009** | DORA/Google Cloud, [Continuous integration](https://dora.dev/capabilities/continuous-integration/) and [Trunk-based development](https://dora.dev/capabilities/trunk-based-development/) capabilities | Living snapshots accessed 2026-08-09 | **Informative research/guidance.** Thresholds in SRC-001 remain provisional local choices. | Per-change builds/tests, fast feedback, Main repair, integration frequency, branch counts/lifetimes | 2026-08-09 | Semiannual; next 2027-02-09 |
| **SRC-010** | GitHub, [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) and [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets) | GitHub living documentation snapshot accessed 2026-08-09 | **Authoritative platform reference.** Describes GitHub enforcement/evidence, not a vendor requirement in 0.1.0-draft. | Required reviews/checks, merge methods, signed commits, deletion/force-push control, bypass/rule behavior | 2026-08-09 | Quarterly; next 2026-11-09 |
| **SRC-011** | GitHub, [Deployments GraphQL model](https://docs.github.com/en/graphql/reference/deployments), [Deployments REST model](https://docs.github.com/en/rest/deployments/deployments), and [deployment history](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/view-deployment-history) | GitHub living documentation; REST API version family `2022-11-28`; snapshot accessed 2026-08-09 | **Authoritative platform reference.** | Commit/ref-to-environment mapping, deployment status/history, production identity and protection evidence | 2026-08-09 | Quarterly; next 2026-11-09 |
| **SRC-012** | GitHub, [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow) | GitHub living methodology snapshot accessed 2026-08-09 | **Authoritative methodology reference.** | GitHub Flow classification: branch, change, PR/review/check, merge, deletion | 2026-08-09 | Semiannual; next 2027-02-09 |
| **SRC-013** | GitLab, [Protected branches](https://docs.gitlab.com/user/project/repository/branches/protected/), [protection rules](https://docs.gitlab.com/user/project/repository/branches/protection_rules/), and [protect your repository](https://docs.gitlab.com/user/project/repository/protect/) | GitLab living documentation snapshot accessed 2026-08-09 | **Authoritative platform reference.** | Effective protection, push/merge permission, force/delete behavior, approval, status checks, rule precedence | 2026-08-09 | Quarterly; next 2026-11-09 |
| **SRC-014** | GitLab, [What is GitLab Flow?](https://about.gitlab.com/topics/version-control/what-is-gitlab-flow/) and [GitLab Flow best practices](https://about.gitlab.com/topics/version-control/what-are-gitlab-flow-best-practices/) | GitLab living methodology snapshots accessed 2026-08-09 | **Authoritative methodology reference.** | Main-first features/fixes, production/stable/environment/version branches, downstream promotion and tags | 2026-08-09 | Semiannual; next 2027-02-09 |
| **SRC-015** | Paul Hammant et al., [Trunk Based Development](https://trunkbaseddevelopment.com/), [short-lived feature branches](https://trunkbaseddevelopment.com/short-lived-feature-branches/), and [branch for release](https://trunkbaseddevelopment.com/branch-for-release/) | Site/book snapshot accessed 2026-08-09; site material identifies 2017–2020 authorship/contributions and remains living | **Authoritative methodology reference.** | Short-lived work, Main integration, late release branches, Main-first fixes, branch deletion | 2026-08-09 | Annual; next 2027-08-09 |
| **SRC-016** | Vincent Driessen, [A successful Git branching model](https://nvie.com/posts/a-successful-git-branching-model/) | Original 2010 GitFlow model with **2020-03-05 reflection** advising simpler flow for continuous-delivery web applications | **Authoritative methodology reference.** Not a universal recommendation. | GitFlow Main/develop/feature/release/hotfix topology and appropriate-use caveat | 2026-08-09 | Annual; next 2027-08-09 |
| **SRC-017** | Git project, *Pro Git*, 2nd ed., [Distributed Workflows](https://git-scm.com/book/en/v2/Distributed-Git-Distributed-Workflows) and [Maintaining a Project](https://git-scm.com/book/en/v2/Distributed-Git-Maintaining-a-Project) | Second edition online snapshot accessed 2026-08-09 | **Authoritative Git workflow reference.** | Centralized, integration-manager/forking, dictator/lieutenants, topic/integration branches, canonical repository | 2026-08-09 | Annual; next 2027-08-09 |
| **SRC-018** | GitHub, [Setting up a project for healthy contributions](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions) | GitHub living documentation snapshot accessed 2026-08-09 | **Authoritative platform/community reference; informative to 0.1.0-draft.** | README, contributing, license, support, security, code of conduct and community-profile evidence | 2026-08-09 | Semiannual; next 2027-02-09 |
| **SRC-019** | Semantic Versioning, [SemVer specification](https://semver.org/) | **Semantic Versioning 2.0.0** | **Normative — conditional.** Binding only for repositories that declare SemVer and a public API; otherwise informative. | Immutable released versions, public API/version compatibility, tags/version labels | 2026-08-09 | Annual and on specification release; next 2027-08-09 |
| **SRC-020** | SPDX/Linux Foundation, [SPDX](https://spdx.dev/) and [SPDX Specification v3.0.1](https://spdx.dev/wp-content/uploads/sites/31/2024/12/SPDX-3.0.1-1.pdf) | **SPDX 3.0.1**, stable specification; SPDX 3.1 was release-candidate material and is not adopted by 0.1.0-draft | **Normative — conditional syntax.** Binding for an SPDX conformance claim; otherwise an authoritative SBOM option. | Dependency inventory, SBOM identity, artifact/release metadata | 2026-08-09 | Quarterly while 3.1 matures, then on stable release; next 2026-11-09 |
| **SRC-021** | CNCF OpenGitOps, [GitOps Principles](https://opengitops.dev/) and [versioned principles repository](https://github.com/open-gitops/documents/blob/v1.0.0/PRINCIPLES.md) | **GitOps Principles v1.0.0**, stable; site snapshot accessed 2026-08-09 | **Authoritative methodology reference.** Defines declarative, versioned/immutable, automatically pulled, continuously reconciled GitOps behavior; informative to the health score unless conformance is claimed. | GitOps promotion classification, CGD-05 profile tests, cadence-relative reconciliation, RLP-02 ref lifecycle | 2026-08-09 | Annual and on principles release; next 2027-08-09 |

## 3. Source-to-control crosswalk

| Source family | Primary control coverage |
|---|---|
| BCP 14 (SRC-002) | Normative language for every control |
| NIST SSDF (SRC-003) | SPI, BTC, CGD, SSC, OWM, RRO outcome rationale |
| OSPS Baseline (SRC-004) | SPI-01/03, BTC-02/03, CGD-01/02/03/04/06, SSC-01/02/03/04, OWM-01/04, DCR-01/02/03/04, RLP-01/03 |
| SLSA 1.2 (SRC-005) | SPI-02/03, BTC-01, CGD-01/02/03/06, SSC-04, RRO-01/03, RLP-01/04 |
| OpenSSF Scorecard (SRC-006) | CGD-02/03/04, SSC-01/02/03/04, OWM-03/04, RLP-03; heuristic only |
| DORA (SRC-007/008/009) | SPI-01, BTC controls, OWM-03, RRO-02/04, and separate DORA panel |
| GitHub/GitLab platform docs (SRC-010/011/013) | Effective enforcement and deployment evidence patterns across SPI, CGD, SSC, RRO |
| Workflow sources (SRC-012/014/015/016/017/021) | CGD-05, DCR-02, and RLP-02 methodology classification/documentation, including GitOps promotion/reconciliation; never used as a universal workflow mandate |
| Community/documentation guidance (SRC-018) | OWM and DCR controls, RLP-03 |
| SemVer/SPDX (SRC-019/020) | Conditional release/version and inventory/SBOM conformance |

## 4. Refresh procedure

At each due date, the standards steward must:

1. Confirm the URL, status, version, publication/update date, and supersession notice from the primary publisher.
2. Compare changed normative clauses or platform behavior with the controls and measures that cite the source.
3. Record “no material change” or open a versioned standards decision; never edit a threshold merely because a vendor heuristic changed.
4. Re-check that DORA remains separate from the health score and that OpenSSF Scorecard aggregate scores are not substituted for control evidence.
5. Update the pin, access date, affected-control crosswalk, and next review only in a new register version.
6. Retain the prior register so an assessment can be replayed against the sources in force when it was issued.

## 5. Known watch items at 0.1.0-draft

- Monitor NIST SP 800-218 Rev.1 / SSDF 1.2 for final publication before considering adoption.
- Monitor the next OSPS Baseline “current” version and map changes by stable control ID.
- Monitor OpenSSF Scorecard v6 work, but continue consuming structured behaviors rather than its aggregate score.
- Monitor SPDX 3.1 until it becomes a stable adopted specification.
- Revisit DORA definitions after the next research update without retroactively changing previously reported outcome data.
- Monitor OpenGitOps principles releases; methodology changes require an explicit profile/schema decision rather than silently changing owner-approved cadence contracts.
