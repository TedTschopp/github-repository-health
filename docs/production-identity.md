# Production Identity and Delivery Resolution

**Standard version:** 0.1.0-draft  
**Generic record schema:** `RH-PRODUCTION-IDENTITY-2.0`  
**Resolution schema:** `RH-DELIVERY-RESOLUTION-1.0`

A production identity record tells the assessor exactly what output or production state to resolve. It is a selector and expected-identity contract, not proof that the selected output exists, is current, or came from the declared source.

The record is committed at `.github/repository-health-production.json` and is read from the exact assessed Main revision. A caller-supplied or working-tree-only record cannot replace it.

## Supported schemas

`RH-PRODUCTION-IDENTITY-1.0` is the narrow release profile used by this standards repository. It selects the controlled-version GitHub Release and names all required release, checksum, source-identity, SBOM, and attestation assets. Its behavior remains supported for compatibility.

`RH-PRODUCTION-IDENTITY-2.0` is the generic, per-unit contract. Its top-level fields are:

| Field | Requirement |
| --- | --- |
| `schema_version` | Exactly `RH-PRODUCTION-IDENTITY-2.0`. |
| `standard_version` | Must equal the assessment configuration and catalog version. |
| `repository` | Exact GitHub `owner/name` being assessed. |
| `units` | One nonempty record for every declared deployable or publishable unit, with no duplicate unit IDs. |

Every unit declares a stable `unit_id`, a profile, lifecycle, correspondence contract, immutable source revision when applicable, a discriminator-specific selector, validation requirements, and retained limitations. Unknown fields, duplicate JSON keys, mutable aliases, ambiguous refs or paths, malformed URLs, invalid digests, conflicting unit lists, and incomplete selectors fail validation.

The common unit fields are exact rather than extensible:

| Field | Contract |
| --- | --- |
| `unit_id` | Must occur exactly once and must match one configured deployable unit. |
| `profile` | Selects one of the six controlled discriminator contracts below. |
| `lifecycle` | Active-output, no-output, and archived profiles each allow only their documented lifecycle set. |
| `correspondence` | Active profiles use `Exact-Main`, `Releasable-Main`, or `Production-Ref`; inactive profiles use `N/A`. |
| `source_sha` | Lowercase full Git SHA for an active output; `null` for approved no-output and archive profiles. |
| `selector` | Contains only the exact fields permitted by the selected profile. |
| `validation` | Must agree with the configured authoritative checks and fail incomplete system-of-record evidence to Unknown. |
| `limitations` | Bounded string array retained in downstream facts and reports. |

## Generic profiles

| Profile | Selected system and identity | Additional proof required for resolution |
| --- | --- | --- |
| `application-github-deployment` | Exact GitHub deployment ID, environment, source SHA, terminal status, artifact reference, and SHA-256 digest. | Complete deployment/status population plus an exact unit-bound evidence statement whose authoritative source and deployed artifact binding are verified. |
| `package-github-release` | Exact release ID and tag, publication policy, source SHA, and complete named artifact/digest set. | Release/tag peel, downloaded-byte digests, Main reachability, and either a verified release statement or verified source-binding attestation for the complete artifact set. |
| `gitops-production-ref` | Exact production ref, ref commit, repository path, and content SHA-256. | Complete ref/content observation plus a verified unit-bound reconciliation statement from the controller system of record. |
| `documentation-publication` | Exact Pages or deployment ID, environment, publication URL, content SHA-256, and terminal status. | Complete publication/deployment record plus a verified unit-bound statement that binds the published content digest. |
| `approved-no-current-output` | Governed decision, approver, dates, rationale, and consumer-discovery record. | Independent governance, delivery, and consumer evidence. The committed declaration cannot approve its own N/A result. |
| `archived-retired` | Governed archive/retirement disposition, last-known source/output, effective date, and write-protection assertion. | Independent lifecycle, write-protection, disabled-delivery, credential, consumer, and retention evidence. The declaration alone cannot pass retirement controls. |

## Selector contracts

| Profile | Required selector identity |
| --- | --- |
| `application-github-deployment` | `github-deployments`, `exact-deployment-id`, exact environment and positive deployment ID, required `success`, plus artifact reference and SHA-256. |
| `package-github-release` | `github-releases`, `exact-release-id-and-tag`, positive release ID, immutable non-alias tag, explicit draft/prerelease policy, and a complete unique artifact list with exactly one primary asset. |
| `gitops-production-ref` | `git`, `exact-ref-commit-and-path`, fully qualified production ref, exact ref commit equal to `source_sha`, safe repository path, and content SHA-256. |
| `documentation-publication` | `github-pages` with an exact Pages deployment ID, or `github-deployments` with a positive deployment ID; both require an environment, HTTPS publication URL, content SHA-256, and `success`. |
| `approved-no-current-output` | Governance decision ID, approver, approval and review dates, reason, and consumer-discovery record. |
| `archived-retired` | Archive decision and disposition, approver, effective date, last-known source SHA and output, plus an asserted write-protected state. |

The validation object repeats the exact configured authoritative checks and requires independent system-of-record proof. Active profiles require Main reachability and the controlled intervening-revision policy. No-output and archive profiles use their type-specific Main policy. All profiles require `incomplete_system_of_record_result: "Unknown"`.

## Resolution rules

An active unit resolves only when all applicable components agree:

1. The relevant system-of-record population is complete and repository-scoped.
2. The unit selector identifies exactly one live record. In a monorepo, selector identities must be unique across units; unscoped evidence cannot be reused for multiple units.
3. The observed source revision, target, status, artifact or content identity, and declared selector match exactly.
4. Any evidence statement is bound to the same repository, unit, source SHA, workflow/run identity, controlled category policy, result, authoritative source record, and artifact/content digest.
5. The source revision is reachable from exact Main. `Releasable-Main` additionally requires every intervening accepted Main revision to have passed every authoritative check.
6. Duplicate, conflicting, partial, inaccessible, stale, or unsupported evidence yields Unknown. Input order and “latest wins” are never conflict-resolution rules.

Repository aggregation uses the worst applicable unit. Evidence for unit A cannot satisfy unit B, and one Unknown unit keeps a repository-level production result Unknown.

## Evidence statements

The companion [Evidence Producer](evidence-producer.md) creates unit-bound validation, security, release, and deployment statements. A well-formed statement is still only a candidate. The collector must independently validate the artifact package, Actions run, source records, controlled category policy, result, and artifact binding before a delivery resolver can consume it.

For deployment and publication, a successful status without an artifact or content binding is insufficient. For packages, a declared subset of release assets is insufficient when the selector defines the complete material artifact population.

## Inactive and no-output units

Low activity, an empty Releases API response, `has_current_output = false`, or `production_correspondence = "N/A"` does not prove that no supported output or consumer exists. These are classification inputs only. Evidence-backed N/A requires the type-appropriate discovery and approval facts described by the control catalog and exception policy.

## Current integration status

The exact-Main production-identity loading seam dispatches both v1 and v2, and the release-asset collector can derive a bounded download allowlist from either schema's declared package assets. Generic declarations are validated against the repository configuration before collection; a working-tree-only or malformed record cannot widen the collector.

The v2 declaration validator, selector-bound delivery collector, and pure fail-closed `RH-DELIVERY-RESOLUTION-1.0` resolver are available for controlled integration testing. The collector supports controlled application deployments, package releases, GitOps refs, and the GitHub Pages form of documentation publication; it rejects bare self-asserted external rows unless a separate authenticated batch verification binds the exact record set. The resolver requires a complete, repository-scoped `RH-GITHUB-DELIVERY-INVENTORY-1.0`; collector-owned `RH-EVIDENCE-STATEMENT-VERIFICATION-1.0` or controlled attestation bindings; exact Main ancestry; and, for `Releasable-Main`, the complete intervening authoritative-check population. It resolves per unit and preserves component-level gaps.

The assessment engine does not yet feed every generic profile's complete adapter facts into that resolver or map its result into `M-SPI-02S`, G-02, or scoring. Generic normalization therefore fails closed to Unknown today. Likewise, an evidence policy whose `subject_source` is `production-unit` requires a targeted exact-subject Actions population; the scheduled Main branch window does not satisfy it. These are deliberate integration boundaries, not evidence that production is unhealthy.
