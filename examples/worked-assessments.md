# Worked Assessments: Fictional Desk-Calibration Corpus

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | **Provisional and entirely fictional** |
| Purpose | Exercise scoring, assurance, gates, methodology neutrality, and type-appropriate applicability before a field pilot |

These are constructed desk-regression fixtures, not empirical findings. No repository, evidence item, score, or outcome below represents a real assessment or a completed field pilot. The cases do not calibrate the model and do not replace the real 12-repository, two-assessor pilot defined in [Governance and Pilot](../docs/governance-and-pilot.md).

## Reproduction rules

- Control order and IDs come from the [Control Catalog](../docs/control-catalog.md): SPI-01–SPI-04; BTC-01–BTC-05; CGD-01–CGD-06; SSC-01–SSC-04; OWM-01–OWM-04; DCR-01–DCR-04; RRO-01–RRO-04; and RLP-01–RLP-04. Each case below states a disposition for all 35 controls.
- Rating key: `M/E#` = Met = 100; `P/E#` = Partially met = 50; `U/E#` = Unmet = 0; `?/E0` = Unknown = 0; and `N/A` is excluded only with the stated rationale. The suffix records that control's evidence level.
- Aggregate E0–E4 distributions and assurance calculations below are derived from these control-level suffixes.
- Controls are equally weighted inside each dimension. Applicable dimensions are equally weighted. Calculations use unrounded values; displayed scores use one decimal place.
- Gate mapping is fixed: G-01 = SPI-01; G-02 = SPI-02; G-03 = CGD-01; G-04 = CGD-02. An applicable Partially met or Unmet gate is Fail; E0 is Unknown. Fail or Unknown caps the effective score at 69.0 and therefore D/M1 — Developing, while preserving the raw result.
- Evidence levels E0/E1/E2/E3/E4 contribute 0/25/50/75/100 assurance points. High is at least 75 with no applicable gate below E3; Moderate is 50 to below 75; Low is below 50.
- `RLP-03` is the only N/A control in cases 1–9: those repositories are active or stable-supported, not deprecated, archived, or retired. This rationale is repeated under each case for auditability.

## Corpus summary

| # | Fictional repository | Canonical repository type | Methodology profile | Raw | Gate effect | Effective | Assurance |
| ---: | --- | --- | --- | ---: | --- | --- | --- |
| 1 | Dispatch API | Deployable application | Trunk-based | 96.9 | None | A/M4 — Leading | 83.8 High |
| 2 | Claims Portal | Deployable application | GitHub Flow/short-lived feature branches | 91.7 | G-02 Unknown | 69.0, D/M1 — Developing | 68.4 Moderate |
| 3 | Billing Service | Deployable application | GitFlow | 87.6 | None | B/M3 — Managed | 70.6 Moderate |
| 4 | Customer Web | Deployable application | Environment-branch flow | 94.8 | G-04 Fail | 69.0, D/M1 — Developing | 75.7 High |
| 5 | Stable Codec | Library/package | Release train/multi-version maintenance | 96.9 | None | A/M4 — Leading | 83.8 High |
| 6 | Platform Desired State | Infrastructure-as-code/GitOps | GitOps promotion | 96.9 | None | A/M4 — Leading | 87.5 High |
| 7 | Community SDK | Library/package | Fork/integration-manager | 67.1 | None | D/M1 — Developing | 53.7 Moderate |
| 8 | Risk Model | Data/analytics/model | Direct gated trunk | 88.1 | None | B/M3 — Managed | 69.9 Moderate |
| 9 | Commerce Monorepo | Monorepo | Custom/hybrid | 87.6 | None | B/M3 — Managed | 80.9 High |
| 10 | Standards Mirror | Mirror/fork; Documentation/content facet | Custom/hybrid | 96.8 | G-02 approved N/A | A/M4 — Leading | 76.1 High |
| 11 | Legacy Parser | Archived/retired; former Library/package | Unclassified; historical GitFlow | 100.0 | G-02 approved N/A | A/M4 — Leading | 78.1 High |
| 12 | UI Spike Kit | Template/scaffold; Sandbox/experimental facet | Custom/hybrid | 42.7 | G-02 approved N/A | F/M0 — At Risk | 32.3 Low |

## 1. Dispatch API — strong trunk-based application

**Classification:** Deployable application; lifecycle Active; Trunk-based; Critical.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E4; SPI-02 M/E4; SPI-03 M/E4; SPI-04 M/E4` | `400/4` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 M/E3; BTC-03 M/E3; BTC-04 M/E3; BTC-05 M/E3` | `500/5` | 100.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `600/6` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 M/E4; SSC-03 P/E4; SSC-04 M/E4` | `350/4` | 87.5 |
| OWM | `OWM-01 M/E3; OWM-02 M/E3; OWM-03 M/E3; OWM-04 M/E3` | `400/4` | 100.0 |
| DCR | `DCR-01 M/E2; DCR-02 M/E2; DCR-03 M/E3; DCR-04 M/E3` | `400/4` | 100.0 |
| RRO | `RRO-01 M/E4; RRO-02 P/E4; RRO-03 M/E4; RRO-04 M/E4` | `350/4` | 87.5 |
| RLP | `RLP-01 M/E3; RLP-02 M/E4; RLP-03 N/A; RLP-04 M/E4` | `300/3` | 100.0 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (100 + 100 + 100 + 87.5 + 100 + 100 + 87.5 + 100) / 8 = 96.875 → 96.9`, **A/M4 — Leading**.

**Gate mapping:** G-01/SPI-01 Pass E4; G-02/SPI-02 Pass E4; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. No cap.

**Assurance:** 34 applicable controls; `E0=0, E1=0, E2=2, E3=18, E4=14`. `(2×50 + 18×75 + 14×100) / 34 = 83.8`, **High**.

## 2. Claims Portal — production identity is unknown

**Classification:** Deployable application; lifecycle Active; GitHub Flow/short-lived feature branches; Elevated.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 ?/E0; SPI-03 M/E4; SPI-04 M/E4` | `300/4` | 75.0 |
| BTC | `BTC-01 M/E3; BTC-02 M/E3; BTC-03 M/E3; BTC-04 M/E3; BTC-05 M/E3` | `500/5` | 100.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `600/6` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 M/E4; SSC-03 P/E1; SSC-04 M/E4` | `350/4` | 87.5 |
| OWM | `OWM-01 M/E2; OWM-02 M/E2; OWM-03 M/E2; OWM-04 M/E3` | `400/4` | 100.0 |
| DCR | `DCR-01 M/E2; DCR-02 P/E2; DCR-03 M/E3; DCR-04 M/E2` | `350/4` | 87.5 |
| RRO | `RRO-01 M/E3; RRO-02 M/E3; RRO-03 M/E3; RRO-04 M/E3` | `400/4` | 100.0 |
| RLP | `RLP-01 M/E2; RLP-02 M/E3; RLP-03 N/A; RLP-04 P/E1` | `250/3` | 83.3 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (75 + 100 + 100 + 87.5 + 100 + 87.5 + 100 + 250/3) / 8 = 91.666… → 91.7`, raw **A/M4 — Leading**.

**Gate mapping:** G-01/SPI-01 Pass E3; **G-02/SPI-02 Unknown E0** because the current running artifact cannot be tied to an immutable source revision reachable from Main; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. `Effective = min(91.666…, 69.0) = 69.0`, **D/M1 — Developing**.

**Assurance:** 34 applicable controls; `E0=1, E1=2, E2=7, E3=19, E4=5`. `(2×25 + 7×50 + 19×75 + 5×100) / 34 = 68.4`, **Moderate**.

## 3. Billing Service — managed GitFlow

**Classification:** Deployable application; lifecycle Active; GitFlow; Elevated.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 M/E3; SPI-03 M/E4; SPI-04 M/E4` | `400/4` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 P/E1; BTC-03 M/E3; BTC-04 P/E1; BTC-05 M/E3` | `400/5` | 80.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `600/6` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 P/E4; SSC-03 P/E4; SSC-04 M/E4` | `300/4` | 75.0 |
| OWM | `OWM-01 M/E2; OWM-02 M/E2; OWM-03 P/E2; OWM-04 M/E3` | `350/4` | 87.5 |
| DCR | `DCR-01 M/E2; DCR-02 P/E2; DCR-03 M/E3; DCR-04 M/E2` | `350/4` | 87.5 |
| RRO | `RRO-01 M/E3; RRO-02 P/E3; RRO-03 M/E3; RRO-04 M/E3` | `350/4` | 87.5 |
| RLP | `RLP-01 M/E2; RLP-02 P/E2; RLP-03 N/A; RLP-04 M/E3` | `250/3` | 83.3 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (100 + 80 + 100 + 75 + 87.5 + 87.5 + 87.5 + 250/3) / 8 = 87.604… → 87.6`, **B/M3 — Managed**.

**Gate mapping:** G-01/SPI-01 Pass E3; G-02/SPI-02 Pass E3; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. No cap.

**Assurance:** 34 applicable controls; `E0=0, E1=2, E2=8, E3=18, E4=6`. `(2×25 + 8×50 + 18×75 + 6×100) / 34 = 70.6`, **Moderate**. GitFlow receives neither a bonus nor a penalty.

## 4. Customer Web — uncontrolled production-critical ref

**Classification:** Deployable application; lifecycle Active; Environment-branch flow; Critical.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E4; SPI-02 M/E3; SPI-03 M/E4; SPI-04 M/E4` | `400/4` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 M/E3; BTC-03 M/E3; BTC-04 M/E3; BTC-05 M/E3` | `500/5` | 100.0 |
| CGD | `CGD-01 M/E3; CGD-02 U/E3; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `500/6` | 83.3 |
| SSC | `SSC-01 M/E4; SSC-02 P/E1; SSC-03 M/E4; SSC-04 M/E4` | `350/4` | 87.5 |
| OWM | `OWM-01 M/E2; OWM-02 M/E2; OWM-03 M/E2; OWM-04 M/E3` | `400/4` | 100.0 |
| DCR | `DCR-01 M/E2; DCR-02 P/E3; DCR-03 M/E3; DCR-04 M/E2` | `350/4` | 87.5 |
| RRO | `RRO-01 M/E3; RRO-02 M/E3; RRO-03 M/E4; RRO-04 M/E4` | `400/4` | 100.0 |
| RLP | `RLP-01 M/E3; RLP-02 M/E3; RLP-03 N/A; RLP-04 M/E3` | `300/3` | 100.0 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (100 + 100 + 500/6 + 87.5 + 100 + 87.5 + 100 + 100) / 8 = 94.791… → 94.8`, raw **A/M4 — Leading**.

**Gate mapping:** G-01/SPI-01 Pass E4; G-02/SPI-02 Pass E3; G-03/CGD-01 Pass E3; **G-04/CGD-02 Fail E3** because a production environment ref permits unauthorized pushes and history rewrite. `Effective = min(94.791…, 69.0) = 69.0`, **D/M1 — Developing**.

**Assurance:** 34 applicable controls; `E0=0, E1=1, E2=5, E3=20, E4=8`. `(1×25 + 5×50 + 20×75 + 8×100) / 34 = 75.7`, **High**. High assurance here means the failure is strongly evidenced; it does not mean the repository is healthy.

## 5. Stable Codec — healthy, stable low-activity library

**Classification:** Library/package; lifecycle Stable-supported; Release train/multi-version maintenance; Baseline. The package releases annually; the observation window extends to its last representative maintenance release. Low activity itself receives no score effect.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 M/E4; SPI-03 M/E4; SPI-04 M/E4` | `400/4` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 M/E3; BTC-03 M/E3; BTC-04 M/E3; BTC-05 M/E3` | `500/5` | 100.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `600/6` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 M/E4; SSC-03 M/E4; SSC-04 P/E4` | `350/4` | 87.5 |
| OWM | `OWM-01 M/E2; OWM-02 P/E3; OWM-03 M/E4; OWM-04 M/E4` | `350/4` | 87.5 |
| DCR | `DCR-01 M/E2; DCR-02 M/E2; DCR-03 M/E3; DCR-04 M/E2` | `400/4` | 100.0 |
| RRO | `RRO-01 M/E4; RRO-02 M/E4; RRO-03 M/E4; RRO-04 M/E4` | `400/4` | 100.0 |
| RLP | `RLP-01 M/E4; RLP-02 M/E4; RLP-03 N/A; RLP-04 M/E4` | `300/3` | 100.0 |

**N/A rationale:** `RLP-03` — lifecycle is Stable-supported, not deprecated, archived, or retired.

`Raw = (100 + 100 + 100 + 87.5 + 87.5 + 100 + 100 + 100) / 8 = 96.875 → 96.9`, **A/M4 — Leading**.

**Gate mapping:** G-01/SPI-01 Pass E3; G-02/SPI-02 Pass E4; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. No cap.

**Assurance:** 34 applicable controls; `E0=0, E1=0, E2=4, E3=14, E4=16`. `(4×50 + 14×75 + 16×100) / 34 = 83.8`, **High**.

## 6. Platform Desired State — strong GitOps repository

**Classification:** Infrastructure-as-code/GitOps; lifecycle Active; GitOps promotion; Critical.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E4; SPI-02 M/E4; SPI-03 M/E4; SPI-04 M/E4` | `400/4` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 M/E3; BTC-03 M/E3; BTC-04 M/E3; BTC-05 M/E3` | `500/5` | 100.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E4; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `600/6` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 M/E4; SSC-03 M/E4; SSC-04 M/E4` | `400/4` | 100.0 |
| OWM | `OWM-01 M/E3; OWM-02 M/E3; OWM-03 P/E4; OWM-04 M/E4` | `350/4` | 87.5 |
| DCR | `DCR-01 M/E2; DCR-02 P/E3; DCR-03 M/E3; DCR-04 M/E3` | `350/4` | 87.5 |
| RRO | `RRO-01 M/E4; RRO-02 M/E4; RRO-03 M/E4; RRO-04 M/E4` | `400/4` | 100.0 |
| RLP | `RLP-01 M/E4; RLP-02 M/E4; RLP-03 N/A; RLP-04 M/E4` | `300/3` | 100.0 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (100 + 100 + 100 + 100 + 87.5 + 87.5 + 100 + 100) / 8 = 96.875 → 96.9`, **A/M4 — Leading**.

**Gate mapping:** G-01/SPI-01 Pass E4; G-02/SPI-02 Pass E4 using immutable desired-state and reconciler evidence; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E4. No cap.

**Assurance:** 34 applicable controls; `E0=0, E1=0, E2=1, E3=15, E4=18`. `(1×50 + 15×75 + 18×100) / 34 = 87.5`, **High**.

## 7. Community SDK — controlled fork flow with material weaknesses

**Classification:** Library/package; lifecycle Active; Fork/integration-manager; Baseline.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 M/E3; SPI-03 M/E4; SPI-04 M/E4` | `400/4` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 P/E1; BTC-03 M/E3; BTC-04 P/E1; BTC-05 P/E1` | `350/5` | 70.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 P/E1; CGD-04 P/E1; CGD-05 M/E3; CGD-06 M/E3` | `500/6` | 83.3 |
| SSC | `SSC-01 P/E2; SSC-02 ?/E0; SSC-03 U/E2; SSC-04 U/E2` | `50/4` | 12.5 |
| OWM | `OWM-01 P/E2; OWM-02 P/E2; OWM-03 ?/E0; OWM-04 M/E3` | `200/4` | 50.0 |
| DCR | `DCR-01 M/E2; DCR-02 P/E2; DCR-03 M/E3; DCR-04 M/E2` | `350/4` | 87.5 |
| RRO | `RRO-01 P/E1; RRO-02 ?/E0; RRO-03 M/E4; RRO-04 P/E2` | `200/4` | 50.0 |
| RLP | `RLP-01 M/E2; RLP-02 P/E1; RLP-03 N/A; RLP-04 M/E4` | `250/3` | 83.3 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (100 + 70 + 500/6 + 12.5 + 50 + 87.5 + 50 + 250/3) / 8 = 67.083… → 67.1`, **D/M1 — Developing**.

**Gate mapping:** G-01/SPI-01 Pass E3; G-02/SPI-02 Pass E3; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. No cap; the D is the raw arithmetic result.

**Assurance:** 34 applicable controls; `E0=3, E1=7, E2=10, E3=10, E4=4`. `(7×25 + 10×50 + 10×75 + 4×100) / 34 = 53.7`, **Moderate**. The fork workflow receives no inherent penalty.

## 8. Risk Model — direct gated trunk for a published model

**Classification:** Data/analytics/model; lifecycle Active; Direct gated trunk; Elevated.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 M/E3; SPI-03 M/E4; SPI-04 P/E4` | `350/4` | 87.5 |
| BTC | `BTC-01 M/E3; BTC-02 P/E1; BTC-03 M/E3; BTC-04 P/E1; BTC-05 M/E3` | `400/5` | 80.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `600/6` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 P/E4; SSC-03 M/E4; SSC-04 M/E4` | `350/4` | 87.5 |
| OWM | `OWM-01 M/E2; OWM-02 M/E2; OWM-03 P/E2; OWM-04 M/E3` | `350/4` | 87.5 |
| DCR | `DCR-01 M/E2; DCR-02 P/E2; DCR-03 M/E3; DCR-04 M/E2` | `350/4` | 87.5 |
| RRO | `RRO-01 M/E3; RRO-02 P/E2; RRO-03 M/E3; RRO-04 P/E2` | `300/4` | 75.0 |
| RLP | `RLP-01 M/E2; RLP-02 M/E3; RLP-03 N/A; RLP-04 M/E3` | `300/3` | 100.0 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (87.5 + 80 + 100 + 87.5 + 87.5 + 87.5 + 75 + 100) / 8 = 88.125 → 88.1`, **B/M3 — Managed**.

**Gate mapping:** G-01/SPI-01 Pass E3; G-02/SPI-02 Pass E3 because the complete current output-to-Main chain is demonstrated; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. No cap. The Partially met SPI-04 reflects historical production-correspondence evidence while the current state conforms.

**Assurance:** 34 applicable controls; `E0=0, E1=2, E2=9, E3=17, E4=6`. `(2×25 + 9×50 + 17×75 + 6×100) / 34 = 69.9`, **Moderate**.

## 9. Commerce Monorepo — custom hybrid with multiple units

**Classification:** Monorepo; lifecycle Active; Custom/hybrid; Critical. Unit profiles are Trunk-based for services, Release train/multi-version maintenance for mobile packages, and tagged publication for shared libraries; the repository-wide ingress and promotion axes are explicitly documented.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 M/E4; SPI-03 M/E4; SPI-04 M/E4` | `400/4` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 P/E3; BTC-03 M/E3; BTC-04 P/E3; BTC-05 M/E3` | `400/5` | 80.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 M/E3; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `600/6` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 P/E4; SSC-03 M/E4; SSC-04 M/E4` | `350/4` | 87.5 |
| OWM | `OWM-01 M/E2; OWM-02 M/E2; OWM-03 P/E3; OWM-04 M/E3` | `350/4` | 87.5 |
| DCR | `DCR-01 M/E2; DCR-02 P/E3; DCR-03 M/E3; DCR-04 M/E2` | `350/4` | 87.5 |
| RRO | `RRO-01 M/E4; RRO-02 P/E4; RRO-03 M/E4; RRO-04 P/E4` | `300/4` | 75.0 |
| RLP | `RLP-01 M/E3; RLP-02 P/E3; RLP-03 N/A; RLP-04 M/E4` | `250/3` | 83.3 |

**N/A rationale:** `RLP-03` — lifecycle is Active, so retirement controls are not triggered.

`Raw = (100 + 80 + 100 + 87.5 + 87.5 + 87.5 + 75 + 250/3) / 8 = 87.604… → 87.6`, **B/M3 — Managed**.

**Gate mapping:** G-01/SPI-01 Pass E3; G-02/SPI-02 Pass E4; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. Each gate uses the least healthy result across all units; no unit fails or is unknown, so no cap applies.

**Assurance:** 34 applicable controls; `E0=0, E1=0, E2=4, E3=18, E4=12`. `(4×50 + 18×75 + 12×100) / 34 = 80.9`, **High**.

## 10. Standards Mirror — read-only upstream synchronization

**Classification:** Mirror/fork with Documentation/content facet; lifecycle Mirrored; Custom/hybrid; Baseline. The workflow axes record automated upstream synchronization, a read-only local contribution model, one protected Main, and no independent release. `Upstream-sync/read-only` is context, not a methodology-profile label.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 N/A; SPI-03 N/A; SPI-04 N/A` | `100/1` | 100.0 |
| BTC | `BTC-01 M/E3; BTC-02 M/E3; BTC-03 M/E3; BTC-04 P/E3; BTC-05 M/E3` | `450/5` | 90.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 N/A; CGD-04 M/E3; CGD-05 M/E3; CGD-06 M/E3` | `500/5` | 100.0 |
| SSC | `SSC-01 M/E4; SSC-02 N/A; SSC-03 N/A; SSC-04 M/E4` | `200/2` | 100.0 |
| OWM | `OWM-01 M/E2; OWM-02 P/E4; OWM-03 M/E2; OWM-04 M/E4` | `350/4` | 87.5 |
| DCR | `DCR-01 M/E2; DCR-02 M/E2; DCR-03 M/E3; DCR-04 M/E2` | `400/4` | 100.0 |
| RRO | `RRO-01 N/A; RRO-02 N/A; RRO-03 N/A; RRO-04 N/A` | Excluded | N/A |
| RLP | `RLP-01 M/E4; RLP-02 N/A; RLP-03 N/A; RLP-04 M/E4` | `200/2` | 100.0 |

**N/A rationales:**

- `SPI-02`, `SPI-04`, and `RRO-01–RRO-04` — current discovery confirms no independently deployed, published, applied, distributed, or supported output; G-02 is approved N/A on this current-output fact.
- `SPI-03` — the mirror has no release or publication.
- `CGD-03` — Baseline single-maintainer synchronization uses a protected trusted bot and documented compensating validation.
- `SSC-02` — a fresh discovery run finds no external dependencies; `SSC-03` — there are neither dependencies nor an executable artifact.
- `RLP-02` — the repository has only Main and immutable tags, with no work, release, environment, or maintenance refs; `RLP-03` — lifecycle is Mirrored, not deprecated, archived, or retired.

`Raw = (100 + 90 + 100 + 100 + 87.5 + 100 + 100) / 7 = 96.785… → 96.8`, **A/M4 — Leading**. RRO is excluded and the remaining seven dimensions are re-normalized equally.

**Gate mapping:** G-01/SPI-01 Pass E3 for synchronization, integrity, and content validation; G-02/SPI-02 approved N/A; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. No cap.

**Assurance:** 23 applicable controls; `E0=0, E1=0, E2=5, E3=12, E4=6`. `(5×50 + 12×75 + 6×100) / 23 = 76.1`, **High**. The result describes mirror health, not production-delivery health.

## 11. Legacy Parser — healthy archived state

**Classification:** Archived/retired; former type Library/package; lifecycle Archived; current observed profile Unclassified with Low confidence because no current workflow events exist. The last supported historical profile, GitFlow, is retained as context rather than presented as a current methodology.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 N/A; SPI-03 M/E4; SPI-04 N/A` | `200/2` | 100.0 |
| BTC | `BTC-01 N/A; BTC-02 N/A; BTC-03 M/E3; BTC-04 N/A; BTC-05 M/E3` | `200/2` | 100.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 N/A; CGD-04 N/A; CGD-05 N/A; CGD-06 M/E3` | `300/3` | 100.0 |
| SSC | `SSC-01 N/A; SSC-02 M/E4; SSC-03 M/E4; SSC-04 M/E4` | `300/3` | 100.0 |
| OWM | `OWM-01 N/A; OWM-02 M/E2; OWM-03 N/A; OWM-04 M/E3` | `200/2` | 100.0 |
| DCR | `DCR-01 N/A; DCR-02 N/A; DCR-03 N/A; DCR-04 M/E2` | `100/1` | 100.0 |
| RRO | `RRO-01 N/A; RRO-02 N/A; RRO-03 N/A; RRO-04 N/A` | Excluded | N/A |
| RLP | `RLP-01 M/E2; RLP-02 N/A; RLP-03 M/E3; RLP-04 M/E4` | `300/3` | 100.0 |

**N/A rationales:**

- `SPI-02` and `SPI-04` — an approved current-state inventory shows no deployed, published, distributed, applied, or supported output. The last release is retained only as historical evidence; archive status alone is not the N/A reason. `SPI-03` remains applicable and Met because a historical release exists.
- `BTC-01` and `BTC-02` apply to active repositories; `BTC-04` has no proposed-change validation population. `BTC-03` and `BTC-05` remain applicable to the archive-validation automation.
- `CGD-03` — Baseline single-caretaker archive with no human changes and compensating protected validation; `CGD-04` and `CGD-05` apply to active repositories. G-03 and G-04 remain applicable through `CGD-01` and `CGD-02`.
- `SSC-01`, `OWM-01`, `OWM-03`, `DCR-01`, and `DCR-02` apply to active repositories. `DCR-03` is approved N/A because support is explicitly ended, consumer discovery found none, and no continuing security-response obligation exists.
- `RRO-01–RRO-04` — there is no current supported output, eligible release in the window, deployment, or operational obligation. Historical release preservation is assessed through `RLP-03`.
- `RLP-02` applies to active repositories; `RLP-03` is applicable and Met for the archive.

`Raw = (100 + 100 + 100 + 100 + 100 + 100 + 100) / 7 = 100.0`, **A/M4 — Leading** within the archive profile.

**Gate mapping:** G-01/SPI-01 Pass E3 for readable history, disposition, and restoration validation; G-02/SPI-02 approved N/A under the current-output rule; G-03/CGD-01 Pass E3 for the locked, auditable administrative path; G-04/CGD-02 Pass E3 for protected Main and retained history. No cap.

**Assurance:** 16 applicable controls; `E0=0, E1=0, E2=3, E3=8, E4=5`. `(3×50 + 8×75 + 5×100) / 16 = 78.1`, **High**. No commit or release activity is expected or rewarded.

## 12. UI Spike Kit — declared experiment with poor hygiene

**Classification:** Template/scaffold with Sandbox/experimental facet; lifecycle Experimental; Custom/hybrid; Baseline. There is no supported consumer or production/publication path.

| Dimension | All control dispositions | Points calculation | Score |
| --- | --- | --- | ---: |
| SPI | `SPI-01 M/E3; SPI-02 N/A; SPI-03 N/A; SPI-04 N/A` | `100/1` | 100.0 |
| BTC | `BTC-01 P/E1; BTC-02 P/E1; BTC-03 ?/E0; BTC-04 ?/E0; BTC-05 ?/E0` | `100/5` | 20.0 |
| CGD | `CGD-01 M/E3; CGD-02 M/E3; CGD-03 N/A; CGD-04 U/E1; CGD-05 P/E1; CGD-06 U/E1` | `250/5` | 50.0 |
| SSC | `SSC-01 P/E2; SSC-02 ?/E0; SSC-03 ?/E0; SSC-04 U/E2` | `50/4` | 12.5 |
| OWM | `OWM-01 P/E2; OWM-02 N/A; OWM-03 ?/E0; OWM-04 P/E1` | `100/3` | 33.3 |
| DCR | `DCR-01 P/E2; DCR-02 P/E2; DCR-03 N/A; DCR-04 M/E2` | `200/3` | 66.7 |
| RRO | `RRO-01 N/A; RRO-02 N/A; RRO-03 N/A; RRO-04 N/A` | Excluded | N/A |
| RLP | `RLP-01 ?/E0; RLP-02 U/E2; RLP-03 N/A; RLP-04 P/E2` | `50/3` | 16.7 |

**N/A rationales:**

- `SPI-02` and `SPI-04` — approved current discovery confirms no production, publication, distribution, applied state, or supported consumer; `SPI-03` — no release or publication exists.
- `CGD-03` — Baseline single maintainer with documented ownership and compensating validation.
- `OWM-02` — documented classification finds no designated critical path.
- `DCR-03` — this explicitly unsupported experiment has no support or security-response commitment; rights documentation in `DCR-04` remains applicable.
- `RRO-01–RRO-04` — never-released experiment with no deployment, publication, current output, or operational obligation.
- `RLP-03` — lifecycle is Experimental, not deprecated, archived, or retired.

`Raw = (100 + 20 + 50 + 12.5 + 100/3 + 200/3 + 50/3) / 7 = 42.738… → 42.7`, **F/M0 — At Risk**.

**Gate mapping:** G-01/SPI-01 Pass E3 under the declared template-instantiation validation contract; G-02/SPI-02 approved N/A; G-03/CGD-01 Pass E3; G-04/CGD-02 Pass E3. No cap; the raw F remains effective.

**Assurance:** 24 applicable controls; `E0=7, E1=6, E2=8, E3=3, E4=0`. `(6×25 + 8×50 + 3×75) / 24 = 32.3`, **Low**.

## Desk-regression observations

- Cases 1, 5, 6, 10, and 11 demonstrate that strong outcomes are attainable across different repository types and canonical methodology profiles.
- Cases 2 and 4 preserve attractive raw scores while a non-compensable foundational gate produces the D/M1 cap.
- Case 4 shows that assurance and health are independent: strong evidence can demonstrate a serious failure.
- Cases 5 and 11 show that stable low activity and intentional archival state are not failures by themselves.
- Cases 10–12 exercise approved N/A normalization without inventing deployment obligations. Case 11 applies G-02's current-output rule rather than treating all archives as automatically N/A.
- These fixtures establish arithmetic reproducibility only. A completed, independently reviewed field pilot is still required before any claim of enterprise calibration.
