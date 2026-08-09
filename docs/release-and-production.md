# Release and Production Correspondence

**Standard version:** 0.1.0-draft  
**Status:** Current published-unit record  
**Evidence boundary:** GitHub Release publication, not a deployed service

## 1. Purpose

This document defines what "production" means for this repository and how an assessor resolves it without relying on a person's recollection. The repository publishes a documentation and assessment package; it does not operate a runtime service. Its production state is therefore the current supported immutable GitHub Release.

The declaration in [`.github/repository-health.toml`](../.github/repository-health.toml) uses the canonical **Releasable-Main** contract. The machine-readable [production identity record](../.github/repository-health-production.json) supplies the resolver and current release identity. Main may be ahead of the published package, but every supported published revision must be immutable and reachable from Main.

## 2. Published unit contract

| Field | Contract |
| --- | --- |
| Unit ID | `github-repository-health` |
| Repository type | Documentation/content |
| Published target | Public GitHub Release in `TedTschopp/github-repository-health` |
| Correspondence | `Releasable-Main` |
| Source resolver | The protected tag formed from `v` plus the controlled `[standard].version` value |
| Artifact resolver | The source package and evidence records attached to that immutable release |
| Required source relationship | The tag resolves to an immutable commit that is Main or an ancestor of Main |
| Required validation | `Validate repository` succeeded for the exact tagged commit before publication |
| Required evidence set | Source package, SPDX 2.3 SBOM, release identity, `SHA256SUMS`, and GitHub artifact-attestation bundle |
| Rollback analogue | Restore support for a previously published immutable release without moving its tag or replacing its assets |
| Roll-forward | Publish a new protected version tag and a new immutable release |
| Withdrawal | Preserve the release and its evidence, but record that it is unsupported and identify a successor or reason in a Main-branch change |

No mutable `latest` label, branch name, workflow artifact, local file, or verbal assertion is a production identity under this contract.

## 3. Current supported publication

The current supported publication is [v0.1.0-draft](https://github.com/TedTschopp/github-repository-health/releases/tag/v0.1.0-draft), published as an immutable prerelease on 2026-08-09.

| Identity | Verified value |
| --- | --- |
| GitHub release ID | `367601330` |
| Version tag | `v0.1.0-draft` |
| Source ref | `refs/tags/v0.1.0-draft` |
| Source SHA | `e1fe796eb2a4e472607bc11503a2364b02818160` |
| Source archive SHA-256 | `f6613cc472837095548d8e3b58b864e1ee6930c0366e90ca4fa942b1f34cca59` |
| SPDX SBOM SHA-256 | `968c153e291ba7e7ccbf51ff300c2c9b2492944e37ef46b0eca2f05e85a875c7` |
| Release identity SHA-256 | `37a865ff1dc2e360da266c22417011ed8bff10f160ced47b023415942b46aeb1` |
| Checksum manifest SHA-256 | `cb30f4b6e38cbb5306f9e32dfc91dacec1199c61a400ea163c225b463843d08c` |
| Attestation bundle SHA-256 | `76f597cb17659fdc7646f41881e5ee1a514f55a7521a3f93c31ea69b23b9ee96` |
| Attestation predicate | `https://spdx.dev/Document/v2.3` |
| Attested subject | Source archive at the SHA-256 above |

GitHub's immutable-release attestation covers the protected tag object and all five release-asset digests. The separate Sigstore SBOM attestation proves that GitHub's OIDC-backed `release.yml` recovery workflow on Main signed the archive/SPDX statement and that the statement was recorded in the transparency log. The release identity and checksum manifest connect that archive to the tag and source SHA. These are complementary records: the custom SBOM attestation is valid artifact authentication, but its workflow-signing commit is not the released source revision and it is not SLSA source provenance for that revision.

The immutable tagged source predated this current-state declaration and its copy of `.github/repository-health.toml` still said `Unknown`. Current Main establishes the `Releasable-Main` contract after publication. This contradiction remains a documented limitation for the first draft release rather than being rewritten or hidden.

## 4. Deterministic verification

An automated assessor resolves the current publication in this order:

1. Read the unit ID and `Releasable-Main` contract from the versioned repository configuration and parse the versioned production identity JSON.
2. Derive the expected tag from `v` plus `[standard].version`; require the production record to name that tag, then fetch its exact release ID rather than an unqualified `latest` alias.
3. Require a published, non-draft release with GitHub's immutable flag set.
4. Resolve the protected tag to its commit and prove the commit is reachable from the current Main history.
5. Require the complete evidence set and compare GitHub's asset digests with `SHA256SUMS` and the release identity record.
6. Verify GitHub's immutable-release attestation against the tag object and every release asset digest.
7. Verify the Sigstore bundle for the archive using the SPDX 2.3 predicate, the canonical repository, and `.github/workflows/release.yml` as signer; report its signer ref/SHA separately from the artifact source SHA.
8. Require the release identity's repository, tag, source SHA, standard version, correspondence contract, archive digest, and SBOM digest to agree with the independently resolved values.
9. Enumerate every accepted Main revision after the released source through the assessed Main SHA and require a successful terminal result for every configured authoritative check on each exact revision. Incomplete Main history, incomplete check enumeration, or any nonterminal result makes correspondence Unknown; a failed result makes it nonconforming.

Any absent item, inaccessible API, digest conflict, mutable release, tag mismatch, unreachable source SHA, or invalid signature makes G-02 **Unknown** or **Fail** according to the measurement dictionary. It must not be converted to Pass by this document alone.

## 5. Supersession and retention

A later supported release supersedes this one only through a reviewed Main change that updates both the structured identity record and this explanatory document after the new immutable release has been independently verified. Prior releases, tags, digests, and attestations remain retained as historical evidence. A failed or interrupted publication does not change the current supported publication.

The initial 0.1.0-draft release is provisional trial material. Its publication does not make the standard calibrated, certified, or suitable as a release/compliance gate.
