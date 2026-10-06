# ESSRF: Evidential Sparse Subset-Routed Fusion for Robust Multimodal 3D Perception

## 0. Lab implementation status and decision record

**Status (2026-10-06): static implementation and controls exist; SF-12 comparison in progress.**
The observation-only `baseline-v1` detectors and independent 3D evaluator passed
SF-11 acceptance. IR-only is the strongest baseline; simple fusion does not beat
it ([results](evidence/SF-11-learning-pilot.md)). See
[baseline profile](LEARNING_BASELINES.md). `backend/learning/essrf_*.py` implements
the static model and validation-only pilot. Initial clean controls show a query
budget/convergence problem, and full training at 40 epochs loses clean accuracy.
These observations do not settle robustness or the architecture's eventual merit. Sections
1–7 describe the research target; this section defines how it is implemented
and tested in the sensor-fusion lab. The [architecture](ARCHITECTURE.md),
[data contracts](DATA_CONTRACTS.md), and [backlog](BACKLOG.md) specify the system
around the model. No theoretical routing identity guarantees detection accuracy.

### 0.1 Implementation profiles

| Profile | Scope | Backlog gate |
| --- | --- | --- |
| `baseline-v1` | RGB-only, IR-only, LiDAR-only and simple fusion detectors with a common evaluator | SF-11 |
| `essrf-static-v1` | Compact frame-wise sparse queries, local modality features, evidential reliability, eight subset experts and explicit null abstention | SF-12 |
| `essrf-temporal-v1` | Temporal query bank, motion/state covariance, calibration-aware local sampling and gated measurement update | SF-14 |

The static profile deliberately omits temporal propagation and learned calibration
uncertainty. It cannot claim those properties merely by using the ESSRF name.
The final target includes the temporal profile; a different final architecture
requires measured justification and an explicit document/backlog revision.

Measured working static configuration: Q=32 learned discovery queries, C=128,
s=16 local samples per query/modality, lightweight image encoders, and a bounded
sparse point encoder (at most 8,192 observed points). Use the 640x384 pilot
images. The original Q=128 was a starting choice, not a validated optimum; it
reached only 0.048 validation mAP in the 40-epoch clean control, versus 0.288
with Q=16. The additional clean Q32 control reached .400 (non-deterministic CUDA
sampling). After repairing sampling, the matched curriculum pilots gave clean /
degradation macro mAP .118 / .062 at Q16 and .314 / .177 at Q32. Q32 was selected
before confirmatory seeds 12/13; it is the model/CLI default. Q16 remains an
explicit ablation, not a universal optimum. Query reference
positions are learned or initialized from declared rig range/frustum geometry,
never from simulator object centers. Empty/off-image neighborhoods have validity
masks and finite outputs. The subset experts are small adapters, not eight copies
of the backbones. Profile memory and end-to-end latency, including encoders,
sampling and host/device transfer, rather than quoting attention-pair ratios.

For static detection, the null expert represents no supported observation and
abstains from emitting new detections. For temporal detection it preserves the
propagated prior and labels continued tracks as prediction-only. All-unavailable
inputs cannot generate an apparently observed object. The initial yaw-only box
head supports upright objects; the dataset retains full 3D orientation. Non-yaw
poses require an explicit head/profile change and evaluation, not silent dropping
of pitch/roll labels.

### 0.2 Inputs and supervision boundaries

Inputs are RGB sensor images, linear calibrated IR, observed sparse LiDAR points,
nominal sensor calibration/timestamps, modality availability, and (for temporal
inference) the model's own previous state. The dataloader and API must enforce
the observation-only contract. Never provide instance masks, object lists, true
boxes, clean hidden surfaces, exact perturbed calibration, or weather/thermal
truth to proposal generation, feature extraction or reliability inference.

Supervision may use simulator truth through matching and losses. Current-frame
positives follow the visibility policy in DATA_CONTRACTS: tight visible 2D masks/
boxes and amodal 3D boxes for geometrically observable objects. A fully hidden
object is not a discovery target. Severe sensor corruption does not erase a
geometrically visible target from evaluation. Track continuation is scored
separately from new detections.

Per-query reliability is not a synonym for global weather severity. Define local
targets using versioned sensor-support/corruption criteria and clean-versus-
corrupted reference comparisons available ONLY during supervision. Document
unlabeled/ambiguous reliability cases and their loss masks. Use modality dropout,
localized corruptions and explicit OOD exposure. Report predictive reliability
calibration and vacuity separately; evidence parameterization alone is not a
calibration guarantee.

### 0.3 Subset isolation and training sequence

An expert for subset S must not consume an excluded current-frame modality
indirectly through shared proposal coordinates, discovery scores, query features,
or fused preprocessing. The initial learned discovery queries are independent
of current sensor inputs. If unimodal proposals are later used, form each
subset's proposals from its own modalities and record provenance. A temporal
prior may summarize past observations; this is explicitly conditional on history,
not a current-frame surviving-sensor-only claim.

1. Validate labels and overfit a tiny scene set with baseline detectors.
2. Train the mixture on clean full-sensor frames for eight epochs, with no
   subset or reliability auxiliary loss. The mixture is optimized from epoch one.
3. Over the next sixteen epochs linearly introduce modality dropout, local known
   corruption (final probability .25 per modality), unlabelled OOD exposure (.10),
   subset loss (final weight 1) and evidential loss (final weight 1). Final dropout
   samples exactly 70% full-sensor frames; the other 30% are uniform over patterns
   0–6. Hardware-unavailable sensors stay unavailable. Monitor routing collapse,
   per-epoch pattern/expert/corruption counts and unsupported confident evidence.
4. Introduce temporal and calibration objectives only after the static profile
  has a measured baseline. Select hyperparameters on grouped validation data.

For the empty subset, supervise static abstention rather than forcing a detector
with no observations to recover current-frame truth boxes. In the temporal
profile, supervise prior propagation/uncertainty and track continuation instead.
Keep fully dropped-out examples in failure/abstention evaluation, with the loss
mask and scoring policy stated explicitly. This distinguishes unavailable sensors
from difficult but available observations, which retain detection supervision.

The 40-epoch FP32 budget, AdamW lr .0005, weight decay .0001, batch 32 and
gradient clip 1 remain fixed for the static controls/curriculum. Baselines retain
their accepted lr .001 and profile; equal budget means equal train rows, epochs,
batch size and optimizer-update count, not equal architecture or wall time.
Curriculum checkpoint selection uses clean grouped-validation mAP only after the
final training regime is reached (epochs 24–40). The early clean checkpoint
cannot masquerade as a robustness-trained candidate. `--clean` preserves the
clean control and `--schedule legacy` preserves the old ten-epoch warm-up and
56.25% effective full-sensor distribution. `last.pt` also preserves the final epoch.

The detection objective uses focal gamma 2, no-object weight .15, centre L1 8,
log-extent L1 .5 and yaw cosine .2. Gaussian localization NLL has weight .1;
its mean is detached so it trains variance while L1 trains box means. Evidential
psi NLL and predictive-mean calibration each have weight .1, vacuity .05.
Negative total losses can arise from Gaussian log variance and are not a
convergence guarantee. Reliability targets follow `reliability-targets.v1`.

Matched validation evaluates all eight availability patterns and six fixed local
corruption probes before either profile's preprocessing. The camera rectangle
covers the central quarter of image area; the LiDAR wedge is [-.2,.2] rad in
nominal rig coordinates. Noise is seeded by capture ID and scenario, independent
of batching/model/seed. Targets remain unchanged. Baselines receive zero/masked
missing observations with their original calibration and no added null gate.
OOD probes reuse the unlabelled training exposure family; they do not demonstrate
generalization to a held-out corruption family. Reports retain per-class,
per-condition, false-positive, calibration, localization and routing results.

Start with FP32 reference checks; enable mixed precision only after checking
digamma/evidence/NLL stability, finite gradients and validation equivalence.
New static training uses deterministic PyTorch algorithms and `bilinear-v1`
image sampling: zero-padded align-corners interpolation through deterministic
gather gradients. Both features and sample coordinates remain differentiable.
CPU float64/float32 values and gradients are checked against `grid_sample`, and
complete CUDA backward repeats exactly. The old CUDA grid sampler had identical
forwards but differing gradients (max 1.502e-5 in a fixed-input probe), so one
seed did not specify an exactly repeatable training trajectory. Legacy checkpoints
retain `grid-sample` on reload; `--legacy-sampling` allows explicit old training.
Repaired pilots use fresh artifact roots. Checkpoints freeze the source revision
at training start and record sampler/numerical settings.
Train within the measured GPU budget in ARCHITECTURE. Gradient accumulation,
point limits, resolution and query-count changes are recorded configuration
changes. Raw local point neighborhoods must never be replaced with truth object
crops to make convergence easier.

### 0.4 Corrections to the research formulation

Two qualifications are incorporated directly into the equations below:

- Failed modalities approaching zero remove every expert that requires them.
  The result is generally a mixture over subsets of surviving modalities. It
  collapses to one exact surviving-subset expert only when each survivor's
  reliability also approaches one. This is an algebraic endpoint result,
  conditional on finite, properly isolated expert features and outputs.
- `GRU(q, q)` need not equal q. An unconditional GRU after null fusion therefore
  does not preserve the prior. Section 2.8 now gates the measurement-induced
  recurrent update by observation mass. At zero observation mass it is exactly
  the prior. Measurement covariance updates must obey the same no-information
  condition; uncertainty can still grow during motion propagation.

### 0.5 Evidence and change policy

SF-11 establishes
baseline quality targets; SF-12/SF-14 compare profiles; SF-15 selects and tests
the trained candidate. Report visible 2D and observable-object 3D detection,
per-class/condition/subset results, calibration, abstention, track/outage metrics,
loss curves, seed variation, p50/p95 latency and peak memory.

If convergence, memory, latency or calibration is poor, change the implementation
and this document together. Every decision entry must give: profile/version,
source and dataset hashes, problem evidence, changed encoder/router/loss/box
representation, validation comparison, cost and remaining limitations. Preserve
failed comparisons. A loss decrease or theoretical complexity reduction alone
does not establish improved perception. Final architecture and data-volume
selection must not use the sealed test set.

| Date | Decision | Evidence / status |
| --- | --- | --- |
| 2026-09-21 | Baselines, compact static profile, then full temporal profile | Planning decision; no measured result |
| 2026-09-21 | Qualify surviving-subset limit; gate GRU measurement update | Algebraic correction, implementation tests pending |
| 2026-10-06 | Q=16; mixture-first 8+16 curriculum, exact 70% full sensors; paired raw degradation | Controls: clean Q128 .048, clean Q16 .288, legacy Q16 .134, seed 11 / 40 epochs; three-seed comparison pending |
| 2026-10-06 | Correct rank ties in vacuity AUROC | Equal scores previously returned 0.0; regression requires 0.5. Training is unchanged |
| 2026-10-06 | Deterministic bilinear image sampler; rerun query pilots | CUDA backward nondeterminism measured; equivalent interpolation and coordinate/feature gradients pass reference tests, full CUDA gradients repeat exactly |
| 2026-10-06 | Select Q32 using predeclared paired degradation mean; freeze remaining seeds | Q16 .062 versus Q32 .177 (seed 11); Q32 clean .314. Final epoch deteriorates to clean .057 / degradation .040, so extra epochs are not presumed beneficial. See `evidence/sf12/selected-configuration.json` |

---

## Abstract

ESSRF (Evidential Sparse Subset-Routed Fusion) is a multimodal 3D perception architecture designed for RGB, thermal, and LiDAR sensing under partial sensor failures, spatially localized corruption, calibration drift, transient degradation, and complete loss of trustworthy observations.

The architecture is built around three principles:

\[
\boxed{\text{dense BEV fusion}\rightarrow\text{sparse object-query fusion}}
\]

\[
\boxed{\text{global modality reliability}\rightarrow\text{query-local modality reliability}}
\]

\[
\boxed{\text{normalized weighted fusion}\rightarrow\text{smooth mixture of subset experts}}
\]

The fundamental reasoning unit is therefore not a sensor mapped onto an entire BEV plane, but the tuple

\[
\boxed{
(\text{object hypothesis},\text{modality},\text{time})
}
\]

ESSRF avoids a mandatory dense BEV fusion manifold, represents reliability as local evidential belief rather than a global scalar, propagates temporal hypotheses with uncertainty, incorporates calibration uncertainty directly into local sampling, and routes each query through a smooth mixture of modality-subset experts, including an explicit null expert for the case in which no sensor is trustworthy.

This construction provides three useful properties. First, localized sensor degradation can be represented at the query level instead of being collapsed into a single sensor-wide score. Second, multimodal fusion no longer contains a quadratic \(G^2\) term in the BEV grid size \(G\). Third, as failed modalities approach zero reliability, routing removes experts that require them. It converges exactly to the surviving-subset expert when surviving reliabilities also approach one, and to the temporal/null expert when all reliabilities approach zero. These algebraic properties do not by themselves establish learned detection robustness.

---

# 1. Design Rationale

## 1.1. Why reliability must be evidential rather than merely probabilistic

For binary reliable/unreliable evidence, let

\[
\alpha_m^{+}=e_m^{+}+1,\qquad
\alpha_m^{-}=e_m^{-}+1,
\]

with

\[
S_m=e_m^{+}+e_m^{-}+2.
\]

The corresponding Subjective Logic opinion is

\[
\boxed{
b_m^+=\frac{e_m^+}{S_m},
\qquad
b_m^-=\frac{e_m^-}{S_m},
\qquad
u_m=\frac{2}{S_m}
}
\]

and therefore

\[
b_m^++b_m^-+u_m=1.
\]

The quantity

\[
\frac{\alpha_m^+}{S_m}
=
\frac{e_m^++1}{S_m}
=
b_m^+ + \frac{u_m}{2}
\]

is the Dirichlet predictive mean, not the positive belief mass.

This distinction is important for routing. Under complete ignorance,

\[
e_m^+=e_m^-=0,
\]

which gives

\[
u_m=1,\qquad b_m^+=b_m^-=0,
\]

while the predictive mean remains

\[
\mathbb E[p_m]=\frac12.
\]

A reliability router should not interpret complete epistemic ignorance as \(50\%\) support for reliability. ESSRF therefore routes on the supported reliable belief itself rather than on the predictive mean.

---

## 1.2. The architecture must represent “no trustworthy observation”

Any fusion rule that normalizes sensor scores to sum to one forces the architecture to choose among the available sensors even when all of them are untrustworthy.

For example, if

\[
p_R,p_T,p_L\rightarrow0
\]

and the scores degrade symmetrically,

\[
p_R=p_T=p_L=\epsilon,
\]

then a normalized rule of the form

\[
w_m=\frac{p_m}{p_R+p_T+p_L}
\]

still yields

\[
w_R=w_T=w_L=\frac13
\]

for every \(\epsilon>0\). Consequently,

\[
\lim_{\epsilon\rightarrow0}
\mathbf F_{fused}
=
\frac13\sum_m W_mF_m,
\]

rather than a state representing the absence of a trustworthy measurement.

Safety-critical perception needs the explicit hypothesis

\[
\boxed{\text{none of the modalities is trustworthy}}.
\]

Such a state allows the system to fall back to a temporal prior, increase state uncertainty, or abstain from applying a measurement correction.

---

## 1.3. Global sensor reliability has irreducible approximation error

Real sensor degradation is frequently spatially non-uniform. Thermal washout may affect one object but not another; dirt or water droplets may obscure only part of a camera field of view; sunlight glare is local; LiDAR scattering and sparsity depend on range; reduced LiDAR field of view is spatially localized; and camouflage affects specific objects rather than the entire scene.

Let the oracle reliability of modality \(m\) vary over spatial positions \(j=1,\ldots,G\):

\[
w_m^*(j).
\]

The oracle fusion is

\[
F^*(j)=\sum_m w_m^*(j)F_m(j).
\]

Suppose instead that a fusion model is restricted to one global weight \(\bar w_m\) per modality:

\[
\hat F(j)=\sum_m\bar w_mF_m(j).
\]

For orthonormal modality features,

\[
\langle F_m(j),F_n(j)\rangle=\delta_{mn},
\]

the approximation error becomes

\[
E(\bar w)
=
\sum_j
\left\|
F^*(j)-\hat F(j)
\right\|_2^2
=
\sum_m\sum_j
(w_m^*(j)-\bar w_m)^2.
\]

The minimum is reached at

\[
\bar w_m=
\frac1G\sum_jw_m^*(j),
\]

which gives

\[
\boxed{
E_{\min}
=
G\sum_m
\operatorname{Var}_j[w_m^*(j)]
}
\]

Thus, whenever reliability is spatially heterogeneous,

\[
\operatorname{Var}_j[w_m^*(j)]>0,
\]

a global gate has a non-zero lower bound on approximation error regardless of training quality.

Reliability should therefore be represented at least at the object-query level,

\[
w_{i,m},
\]

and, when necessary, at the local receptive-field level,

\[
w_{i,m,r}.
\]

---

## 1.4. Sparse perception should use sparse fusion

Let

\[
G=H_bW_b
\]

be the number of BEV cells. Dense attention over the BEV plane scales as

\[
O(G^2C).
\]

A representative architecture with three dense cross-modal attention operations followed by one dense BEV self-attention block requires

\[
O(3G^2C)+O(G^2C)
=
\boxed{O(4G^2C)}
\]

attention interaction cost, after image encoding and spatial transformation have already been performed.

For

\[
H_b=W_b=200,
\]

we have

\[
G=40\,000,
\qquad
G^2=1.6\times10^9.
\]

A single materialized fp16 attention score matrix requires

\[
1.6\times10^9\times2
=
3.2\text{ GB/head}.
\]

With eight heads, this becomes

\[
25.6\text{ GB}
\]

for the score matrix of one dense attention block. Memory-efficient attention can avoid materializing the entire matrix, but it does not remove the underlying

\[
O(G^2C)
\]

arithmetic.

The number of object hypotheses is usually much smaller than the number of BEV cells,

\[
Q\ll G.
\]

ESSRF therefore performs fusion around sparse 3D object queries rather than over a dense scene grid. This is consistent with the sparse instance-level direction demonstrated by SparseFusion. [1]

---

## 1.5. Calibration uncertainty is part of fusion uncertainty

Intrinsic and extrinsic calibration should not be treated as exact constants at fusion time.

Consider an angular extrinsic error

\[
\delta\theta=0.5^\circ
\approx8.73\times10^{-3}\text{ rad}.
\]

At

\[
r=80\text{ m},
\]

the induced spatial displacement is approximately

\[
\delta x\simeq r\delta\theta
\simeq0.70\text{ m}.
\]

At BEV resolution

\[
\Delta=0.25\text{ m},
\]

this corresponds to roughly

\[
2.8
\]

cells.

Thus, two fully functioning sensors can produce apparently contradictory local features solely because of calibration drift. A reliability model that does not explicitly represent geometric uncertainty may incorrectly classify misregistration as sensor corruption.

ESSRF therefore propagates calibration covariance into the sampling region used to obtain each local modality observation.

---

## 1.6. Temporal evidence is required for transient degradation

Rain, fog, particulate LiDAR returns, brief glare, and other transient phenomena are often easier to identify through temporal inconsistency than through a single frame.

Let \(X_t\) denote the current frame and \(X_{1:t}\) the full history. The hypothesis class using temporal history contains the current-frame-only class:

\[
\mathcal H(X_t)\subseteq\mathcal H(X_{1:t}).
\]

Therefore the optimal Bayes risk satisfies

\[
\boxed{
R^*(X_{1:t})\le R^*(X_t)
}
\]

for any proper loss.

Temporal information is especially valuable under transient corruption, so ESSRF maintains a temporal query bank and uses a null expert that continues prediction without inventing new measurement information.

---

## 1.7. Formal robustness should follow from architecture, not training heuristics

A graceful-degradation theorem should rely only on assumptions that are explicitly part of the architecture or training objective.

In particular, the proof should not require heuristic implications such as

\[
\text{uniform LiDAR noise}
\Rightarrow
\operatorname{Var}(F_L)\rightarrow0,
\]

because finite-sample voxel occupancy has sampling variance and nonlinear feature extraction can preserve or amplify variation.

Likewise, a constant image does not guarantee spatially constant deep features in the presence of padding, positional transformations, or learned offsets.

Training with modality dropout also does not mathematically imply

\[
e^{unrel}\rightarrow\infty.
\]

That behavior may be encouraged by training, but it is not an architectural identity.

Loss boundedness should be treated with the same care. Focal-style classification losses contain a negative log-probability term and can diverge as

\[
p_y\rightarrow0.
\]

Unrestricted L1 regression is not globally upper-bounded, and

\[
KL(\operatorname{Dir}(\alpha)\Vert\operatorname{Dir}(1))
\]

does not become bounded solely from the constraint

\[
\alpha_k\ge1.
\]

ESSRF therefore derives graceful degradation directly from the subset-routing algebra and handles gradient non-singularity separately.

---

# 2. ESSRF Architecture

Let

\[
\mathcal M=\{R,T,L\}
\]

denote RGB, thermal, and LiDAR modalities.

The core fusion entity is a **3D object query**, not a BEV cell.

## 2.1. Modality-specific encoders

For RGB,

\[
F_R
=
\phi_R(I_R)
\in
\mathbb R^{L_R\times C},
\qquad
L_R=H_fW_f.
\]

For thermal imaging,

\[
F_T
=
\phi_T(I_T)
\in
\mathbb R^{L_T\times C}.
\]

LiDAR remains sparse:

\[
(X_L,F_L)
=
\phi_L(P),
\]

with

\[
X_L\in\mathbb R^{V\times3},
\qquad
F_L\in\mathbb R^{V\times C},
\qquad
V\le N.
\]

A dense LiDAR BEV manifold is not required for multimodal fusion.

---

## 2.2. Sparse temporal query bank

ESSRF maintains \(Q\) queries,

\[
Q_t^-=
[q_1^-,\ldots,q_Q^-]^T
\in\mathbb R^{Q\times C},
\]

with 3D reference states

\[
X_t^-=
[x_1^-,\ldots,x_Q^-]^T
\in\mathbb R^{Q\times3}
\]

and state uncertainty

\[
\Sigma_i^-\in\mathbb S_{++}^{3}.
\]

Temporal queries are propagated by

\[
x_{i,t}^-
=
T_{t-1\rightarrow t}
f_{motion}(x_{i,t-1},v_{i,t-1}),
\]

and

\[
\Sigma_{i,t}^-
=
A_i\Sigma_{i,t-1}A_i^T+Q_{motion}.
\]

Unused slots are filled by top-\(K\) unimodal proposals or learned discovery queries.

---

## 2.3. Calibration-aware local sampling

Instead of lifting every BEV cell, ESSRF samples only the neighborhood of the \(Q\) current hypotheses.

For a camera modality \(m\),

\[
u_{i,m}
=
\pi_m(x_i^-).
\]

Let the calibration perturbation in \(SE(3)\) be

\[
\xi_m\sim\mathcal N(0,\Sigma_m^{cal}).
\]

Linearizing the projection gives

\[
J_{i,m}
=
\frac{\partial \pi_m(T_m(\xi)x_i)}
{\partial\xi}
\Big|_{\xi=0}.
\]

The projected covariance is

\[
\boxed{
\Sigma_{u,i,m}
=
J_x\Sigma_i^-J_x^T
+
J_{i,m}\Sigma_m^{cal}J_{i,m}^T
+
\sigma_{pix}^2I
}
\]

where the first term propagates object-state uncertainty, the second term propagates calibration uncertainty, and the final term captures residual pixel-space uncertainty.

From this uncertainty ellipse, choose \(s\) offsets

\[
\delta_r=L_{i,m}\epsilon_r,
\qquad
L_{i,m}L_{i,m}^T=\Sigma_{u,i,m}.
\]

Local camera features are sampled as

\[
G_{i,m}[r]
=
\operatorname{Bilinear}
(F_m,u_{i,m}+\delta_r),
\]

yielding

\[
G_{i,m}\in\mathbb R^{s\times C}.
\]

For LiDAR,

\[
G_{i,L}
=
\operatorname{KNN}_{s}
\left(
X_L,F_L;
x_i^-,\Sigma_i^-
\right)
\in\mathbb R^{s\times C}.
\]

Calibration uncertainty therefore controls the spatial receptive field directly instead of being hidden inside a generic learned correction.

---

## 2.4. Query-local modality observations

For every query-modality pair \((i,m)\),

\[
a_{i,m}
=
\operatorname{softmax}
\left(
\frac{
(q_i^-W_Q)
(G_{i,m}W_K)^T
}
{\sqrt d}
\right)
\in\mathbb R^{1\times s},
\]

and

\[
h_{i,m}
=
W_O
a_{i,m}
(G_{i,m}W_V)
\in\mathbb R^C.
\]

The local multimodal attention cost is

\[
O(QMsC),
\]

rather than dense fusion over a \(G\times G\) interaction space.

---

## 2.5. Query-local evidential reliability

For each \((i,m)\), define a local reliability descriptor

\[
d_{i,m}
=
[
q_i^-;
\operatorname{Mean}(G_{i,m});
\operatorname{Var}(G_{i,m});
s_{i,m}^{physical};
s_{i,m}^{temporal}
].
\]

The reliability network produces non-negative positive and negative evidence:

\[
(e_{i,m}^{+},e_{i,m}^{-})
=
\operatorname{softplus}
(g_m(d_{i,m})).
\]

Define

\[
S_{i,m}
=
e_{i,m}^{+}
+
e_{i,m}^{-}
+2.
\]

The Subjective Logic masses are

\[
b_{i,m}^{+}
=
\frac{e_{i,m}^{+}}{S_{i,m}},
\]

\[
b_{i,m}^{-}
=
\frac{e_{i,m}^{-}}{S_{i,m}},
\]

and

\[
u_{i,m}
=
\frac2{S_{i,m}},
\]

so that

\[
b_{i,m}^{+}
+b_{i,m}^{-}
+u_{i,m}=1.
\]

ESSRF uses the supported reliable belief for routing:

\[
\boxed{
\rho_{i,m}=b_{i,m}^{+}
}
\]

rather than the predictive mean.

When there is no evidence,

\[
e^+=e^-=0
\Rightarrow
\rho=0,
\quad
u=1.
\]

Ignorance therefore does not become artificial \(50\%\) reliability.

A hardware health bit \(a_m\in\{0,1\}\) can be incorporated as

\[
r_{i,m}=a_m\rho_{i,m}.
\]

---

## 2.6. Smooth subset-of-modalities mixture

For three modalities there are only

\[
2^3=8
\]

modality subsets, including the empty subset:

\[
\emptyset,\ R,\ T,\ L,\ RT,\ RL,\ TL,\ RTL.
\]

For each subset \(S\subseteq\mathcal M\), define a lightweight expert

\[
z_{i,S}
=
D_S
\left(
q_i^-,
\{h_{i,m}:m\in S\}
\right)
\in\mathbb R^C.
\]

Each \(D_S\) is a small decoder or adapter rather than another backbone.

The routing probability is defined **without softmax and without division**:

\[
\boxed{
\pi_{i,S}
=
\prod_{m\in S}r_{i,m}
\prod_{m\notin S}(1-r_{i,m})
}
\]

for every

\[
S\subseteq\mathcal M.
\]

The routing weights are automatically normalized:

\[
\sum_{S\subseteq\mathcal M}\pi_{i,S}
=
\prod_m[r_{i,m}+(1-r_{i,m})]
=
1.
\]

Fusion is

\[
\boxed{
z_i
=
\sum_{S\subseteq\mathcal M}
\pi_{i,S}z_{i,S}
}
\]

This is the central mathematical construction of ESSRF.

It has no normalization denominator, no \(0/0\) failure mode, and no forced selection of a corrupted sensor. In particular,

\[
\pi_{i,\emptyset}
=
\prod_m(1-r_{i,m}),
\]

provides explicit probability mass for the event

\[
\boxed{\text{no trustworthy observation}}.
\]

---

## 2.7. Temporal/null expert

Define

\[
D_{\emptyset}(q_i^-)=q_i^-.
\]

If all sensor reliabilities vanish, then

\[
z_i=q_i^-.
\]

The system adds no new measurement information and continues temporal prediction with increasing uncertainty.

Define the observation mass as

\[
\kappa_i
=
1-\pi_{i,\emptyset}.
\]

A spatial state update can then be written as

\[
x_i^t
=
x_i^-
+
\kappa_i\Delta x_i.
\]

As

\[
\kappa_i\rightarrow0,
\]

the measurement correction vanishes continuously.

---

## 2.8. Detection output

After temporal fusion, gate the measurement-induced recurrent change by the
observation mass \(\kappa_i=1-\pi_{i,\emptyset}\):

\[
\tilde q_i^t
=
\operatorname{GRU}(q_i^-,z_i).
\]

\[
\boxed{
q_i^t=q_i^-+\kappa_i(\tilde q_i^t-q_i^-)
}
\]

Thus \(\kappa_i=0\) implies \(q_i^t=q_i^-\) exactly; an unconditional GRU
would not provide that identity. New-detection emission also requires observation
support. A null update may continue a prior track as prediction-only but cannot
declare a new measurement. At zero observation mass, localization uncertainty
comes from the propagated prior, not a fresh learned variance head.

For the temporal profile, one admissible covariance update is

\[
\Sigma_i^t=
\left[(\Sigma_i^-)^{-1}+\kappa_i\Lambda_i^{meas}\right]^{-1},
\qquad \Lambda_i^{meas}\succeq0.
\]

It preserves \(\Sigma_i^-\) at \(\kappa_i=0\). The positive-semidefinite
measurement information must be estimated/calibrated; the algebra alone does
not make uncertainty calibrated. Motion process noise is applied during prior
propagation as in section 2.2.

Class logits are

\[
\ell_i
=
W_{cls}q_i^t
\in
\mathbb R^{K_{cls}+1},
\]

and the box mean is

\[
\mu_i
=
W_{box}q_i^t
\in\mathbb R^8.
\]

One possible box parameterization is

\[
b=
(x,y,z,\log w,\log l,\log h,\sin\theta,\cos\theta).
\]

Localization variance is predicted as

\[
\sigma_{i,k}^2
=
\sigma_{\min}^2
+
\operatorname{softplus}
([W_\sigma q_i^t]_k).
\]

The fixed lower bound

\[
\sigma_{\min}>0
\]

prevents singular localization variance and is used in the gradient argument below.

---

# 3. Training Objective

## 3.1. Detection loss

After Hungarian matching \(\sigma\),

\[
\mathcal L_{det}
=
\lambda_{cls}\mathcal L_{cls}
+
\lambda_{nll}\mathcal L_{loc}
+
\lambda_{iou}\mathcal L_{IoU}.
\]

Classification uses

\[
\mathcal L_{cls}
=
\sum_i
\operatorname{Focal}
(
\operatorname{softmax}(\ell_i),
c_{\sigma(i)}^*
).
\]

Localization uncertainty is trained with

\[
\boxed{
\mathcal L_{loc}
=
\frac12
\sum_{i\in\mathcal P}
\sum_{k=1}^{8}
\left[
\frac{(b_{i,k}^*-\mu_{i,k})^2}
{\sigma_{i,k}^2}
+
\log\sigma_{i,k}^2
\right]
}
\]

and the geometric term is

\[
\mathcal L_{IoU}
=
\sum_{i\in\mathcal P}
[1-\operatorname{IoU}_{3D}(B_i,B_i^*)].
\]

---

## 3.2. Evidential reliability objective

For a local binary reliability target

\[
y_{i,m}\in\{0,1\},
\]

the expected categorical negative log-likelihood under the Beta/Dirichlet model is

\[
\boxed{
\mathcal L_{rel}^{CE}
=
\psi(S_{i,m})
-
y_{i,m}\psi(\alpha_{i,m}^{+})
-
(1-y_{i,m})\psi(\alpha_{i,m}^{-})
}
\]

where

\[
\alpha^+=e^++1,\qquad
\alpha^-=e^-+1.
\]

The appearance of

\[
\psi(S)
\]

rather than \(\log S\) follows from the expected negative log categorical likelihood under a Dirichlet distribution, consistent with the evidential classification formulation. [2]

For calibration of the predictive reliability mean,

\[
\mu_{i,m}^{rel}
=
\frac{\alpha_{i,m}^{+}}{S_{i,m}},
\]

use

\[
\mathcal L_{cal}
=
(\mu_{i,m}^{rel}-y_{i,m})^2.
\]

Let \(o_{i,m}\) indicate deliberate exposure to OOD or unknown corruption:

\[
o_{i,m}=1
\]

for such samples.

The vacuity objective is

\[
\mathcal L_{vac}
=
(1-o_{i,m})u_{i,m}^2
+
o_{i,m}(1-u_{i,m})^2.
\]

Thus, a known reliable or known unreliable sample is encouraged to accumulate strong evidence of one sign,

\[
u\rightarrow0,
\]

whereas an unknown degradation is encouraged toward

\[
u\rightarrow1.
\]

Evidential uncertainty is therefore not assumed to emerge automatically from a deterministic Dirichlet head; it is trained explicitly using reliability supervision, calibration objectives, and OOD exposure. This is aligned with broader observations in the uncertainty-quantification literature that evidential calibration is not automatic. [3]

---

## 3.3. Subset expert training

Every subset expert that may be selected at inference time must be trained on its own conditional input configuration:

\[
\mathcal L_{subset}
=
\mathbb E_{S\sim p_{train}(S)}
[
\mathcal L_{det}^{S}
].
\]

It is not necessary to evaluate all seven non-empty subset experts in every batch. The subset \(S\) can be Monte-Carlo sampled.

This training term is essential for the formal degradation result: an expert cannot be claimed to represent a useful surviving sub-network unless that input subset is explicitly represented in training.

The temporal loss is

\[
\mathcal L_{temp}
=
\sum_{i\in tracks}
\left\|
x_{i,t}
-
T_{t-1\rightarrow t}
f_{motion}(x_{i,t-1},v_{i,t-1})
\right\|_{Huber}.
\]

The complete objective is

\[
\boxed{
\begin{aligned}
\mathcal L_{total}
={}&
\lambda_{mix}\mathcal L_{det}
+
\lambda_{sub}\mathcal L_{subset}\\
&+
\lambda_{rel}\mathcal L_{rel}^{CE}
+
\lambda_{cal}\mathcal L_{cal}\\
&+
\lambda_{vac}\mathcal L_{vac}
+
\lambda_{temp}\mathcal L_{temp}.
\end{aligned}
}
\]

---

# 4. Formal Properties

## 4.1. Graceful-degradation theorem

Let

\[
r=(r_R,r_T,r_L)\in[0,1]^3.
\]

Define

\[
F(r)
=
\sum_{S\subseteq\mathcal M}
\pi_S(r)F_S
\]

with

\[
\pi_S(r)
=
\prod_{m\in S}r_m
\prod_{m\notin S}(1-r_m).
\]

Let \(A\subseteq\mathcal M\) be the set of surviving modalities. Consider the full-failure limit for every modality outside \(A\):

\[
r_m\rightarrow
\begin{cases}
1,&m\in A,\\
0,&m\notin A.
\end{cases}
\]

For \(S=A\),

\[
\pi_A
\rightarrow
\prod_{m\in A}1
\prod_{m\notin A}1
=
1.
\]

For any

\[
S\neq A,
\]

there exists at least one modality for which the product contains either

\[
r_m\rightarrow0
\]

or

\[
1-r_m\rightarrow0.
\]

Therefore

\[
\pi_S\rightarrow0.
\]

Hence,

\[
\boxed{
F(r)\rightarrow F_A
}
\]

exactly.

If all modalities fail,

\[
A=\emptyset,
\]

then

\[
\boxed{
F(r)\rightarrow F_\emptyset
}
\]

which is the temporal/null expert.

The result follows directly from the routing polynomial; it does not require a learned gate to become infinitely confident under corruption.

If only the failed modalities approach zero, while surviving reliabilities remain
arbitrary, the more general limit is

\[
F(r)\longrightarrow
\sum_{S\subseteq A}
\left[
\prod_{m\in S}r_m
\prod_{m\in A\setminus S}(1-r_m)
\right]F_S.
\]

This is a mixture of experts using surviving modalities, including the null
expert; it is not generally \(F_A\). Both results assume finite expert outputs
and proper subset isolation. A failed current-frame modality must not contaminate
\(q_i^-\), proposal locations or surviving features through another path. The
theorem does not show that a learned reliability head will identify every failure
or that any selected expert has good detection accuracy.

---

## 4.2. Interpretation as the surviving risk-minimizing sub-network

For each modality subset \(S\), define the conditional risk

\[
R_S(\theta_S)
=
\mathbb E[
\mathcal L(
F_S(X_S;\theta_S),Y
)
].
\]

Suppose training obtains

\[
\theta_S^*
\in
\arg\min_{\theta_S\in\Theta_S}
R_S(\theta_S).
\]

Then, for active modality set \(A\),

\[
\lim_{r\rightarrow1_A}
F(r)
=
F_A(X_A;\theta_A^*).
\]

Therefore the architecture converges exactly to the **risk-minimizing sub-network within hypothesis class \(\Theta_A\)**.

This is the strongest claim available without additional assumptions. A finite neural network can only be identified with the absolute Bayes-optimal predictor if both of the following hold:

1. the Bayes predictor belongs to \(\Theta_A\);
2. training reaches the global optimum.

Under those assumptions,

\[
F_A=F_A^{Bayes}.
\]

Without them, the correct claim is risk minimization within the chosen subset-expert hypothesis class.

---

## 4.3. Gradient non-singularity

Subset routing contains no division.

For

\[
\pi_S
=
\prod_m f_{S,m}(r_m),
\]

we have

\[
\left|
\frac{\partial\pi_S}
{\partial r_j}
\right|
\le1.
\]

Reliability is

\[
\rho
=
\frac{e^+}{e^++e^-+2}.
\]

Therefore,

\[
\frac{\partial\rho}{\partial e^+}
=
\frac{e^-+2}
{(e^++e^-+2)^2}
\le\frac12,
\]

and

\[
\frac{\partial\rho}{\partial e^-}
=
-\frac{e^+}
{(e^++e^-+2)^2}.
\]

The derivative with respect to negative evidence is also finite for every

\[
e^\pm\ge0.
\]

For

\[
e=\operatorname{softplus}(z),
\]

\[
0<
\frac{\partial e}{\partial z}
<1.
\]

Thus the router Jacobian remains finite even as

\[
r\rightarrow0
\]

or

\[
r\rightarrow1.
\]

Localization NLL is protected against singular variance because

\[
\sigma^2
=
\sigma_{\min}^2+\operatorname{softplus}(s)
\ge\sigma_{\min}^2>0.
\]

Therefore terms of the form

\[
1/\sigma^2
\]

do not diverge.

Structurally,

\[
\boxed{
\left\|
\frac{\partial F}
{\partial r}
\right\|<\infty
}
\]

for finite expert outputs.

No analogous normalization term of the form

\[
\frac{w_k}{\sum_jw_j+\epsilon}
\]

is required by the router.

---

# 5. Complexity and Deployment

Let

\[
R=HW,
\quad
G=H_bW_b,
\quad
V\le N,
\]

and

\[
Q=\text{number of object queries},
\quad
s=\text{local samples/query/modality}.
\]

Let \(E_r\) denote the number of subset experts actually executed per query.

## 5.1. Asymptotic comparison

The following table compares ESSRF with a representative dense BEV fusion design that performs image-to-BEV transformation, modality-level dense processing, three dense cross-modal attention operations, and one dense BEV self-attention operation.

| Component | Dense BEV fusion | ESSRF |
| --- | ---: | ---: |
| RGB + thermal backbones | \(O(RC^2L)\) | \(O(RC^2L)\) |
| LiDAR encoding | \(O(NC_p)\) | \(O(NC_p)\) |
| Image spatial transform | \(O(GK_hH_aM_pC)\) | \(O(QsC)\) |
| Reliability extraction | \(O(MGC)\) | \(O(MQsC)\) |
| Cross-modal attention | **\(O(3G^2C)\)** | **\(O(MQsC)\)** |
| Global interaction | **\(O(G^2C)\)** | \(O(Q^2C)\) |
| Fusion / expert decode | \(O(MGC)\) | \(O(QE_rC^2)\) |
| Temporal update | not required by baseline | \(O(QC^2)\) |
| Attention memory | **\(O(G^2)\)** | \(O(Q^2+MQs)\) |
| Spatial fusion storage | \(O(MGC)\) | \(O(QC+VC)\) |

The representative dense formulation has complexity

\[
\boxed{
T_{dense}
=
O(
RC^2L
+
NC_p
+
GK_hH_aM_pC
+
4G^2C
+
GC^2
)
}
\]

whereas ESSRF has

\[
\boxed{
T_{ESSRF}
=
O(
RC^2L
+
NC_p
+
MQsC
+
Q^2C
+
QE_rC^2
)
}
\]

The central scaling property is

\[
\boxed{G^2\text{ disappears from multimodal fusion}}
\]

and \(G\) no longer needs to be the representation size of the fusion core.

---

## 5.2. Concrete fusion-core latency proxy

Consider a moderate BEV grid

\[
G=200\times200=40\,000,
\]

with

\[
Q=300,\qquad s=16,\qquad M=3.
\]

A dense fusion core with three dense cross-modal attention operations and one dense BEV self-attention operation performs approximately

\[
3G^2+G^2
=
4(40\,000)^2
=
6.4\times10^9
\]

attention-pair interactions.

ESSRF uses

\[
MQs+Q^2
\]

interactions, giving

\[
3(300)(16)+300^2
=
14\,400+90\,000
=
104\,400.
\]

The ratio is

\[
\boxed{
\frac{6.4\times10^9}{104\,400}
\approx61\,300
}
\]

so the fusion-attention core performs approximately **61,000 times fewer pair interactions** in this proxy.

This does **not** imply a \(61{,}000\times\) end-to-end detector speedup. Once the fusion bottleneck is removed, the RGB/thermal backbones and LiDAR encoder become dominant. The comparison only shows that the fusion architecture itself no longer contains an operation whose asymptotic scaling can dominate edge latency.

For fp16 and eight heads, a materialized dense \(G\times G\) score tensor requires approximately

\[
25.6\text{ GB/block}.
\]

ESSRF query self-attention requires

\[
300^2\times8\times2
\simeq1.44\text{ MB},
\]

while local modality attention requires

\[
3\times300\times16\times8\times2
\simeq0.23\text{ MB}.
\]

The combined score storage is therefore approximately

\[
1.67\text{ MB},
\]

instead of tens of gigabytes in a naive materialized dense implementation.

---

## 5.3. Conditional execution

ESSRF can also reduce latency through conditional computation.

If

\[
a_L=0,
\]

the LiDAR encoder can be skipped entirely.

If

\[
a_T=0,
\]

the thermal backbone can be skipped.

After computing \(\pi_S\), inference does not necessarily need to execute every subset adapter. A top-\(K\) approximation, typically with \(K=1\) or \(K=2\), can retain the highest-probability experts.

If

\[
\|z_S\|\le B
\]

and the retained routing probability mass is

\[
P_K=\sum_{S\in TopK}\pi_S,
\]

then the discarded contribution satisfies

\[
\left\|
\sum_{S\notin TopK}
\pi_Sz_S
\right\|
\le
B(1-P_K).
\]

Thus conditional execution admits an explicit error bound in terms of the discarded probability mass.

---

# 6. Discussion

ESSRF combines five architectural commitments:

- heterogeneous modality-specific encoders;
- explicit geometric reasoning;
- evidential reliability;
- explicit training of modality subsets;
- graceful degradation as a structural design requirement.

The architecture deliberately avoids four constraints that are problematic under realistic sensor degradation:

\[
\text{dense common BEV as a mandatory fusion manifold},
\]

\[
\text{one reliability scalar per modality},
\]

\[
\sum_mw_m=1
\quad
\text{without a null hypothesis},
\]

and

\[
G\times G
\quad
\text{cross-modal attention}.
\]

The sparse representation direction is consistent with prior work such as SparseFusion, while the evidential component follows the Dirichlet/Subjective Logic formulation introduced for evidential deep learning. [1][2] Practical uncertainty calibration still requires explicit objectives and suitable OOD exposure rather than being guaranteed by the parameterization alone. [3]

The main conceptual shift is from reasoning over a sensor as a whole,

\[
\text{sensor}\rightarrow\text{entire spatial fusion plane},
\]

to reasoning over

\[
\boxed{
(\text{object hypothesis},
\text{modality},
\text{time})
}.
\]

This makes it possible to express the operational state that robust multimodal perception most often needs: a sensor may be useful **here**, untrustworthy **there**, and epistemically uncertain for a particular object at the current time.

---

# 7. Conclusion

ESSRF is a sparse, local, temporally aware multimodal fusion architecture for RGB, thermal, and LiDAR perception under sensor degradation.

Its central mechanism is a smooth mixture over all modality subsets,

\[
\pi_{i,S}
=
\prod_{m\in S}r_{i,m}
\prod_{m\notin S}(1-r_{i,m}),
\]

combined with query-local evidential reliability and an explicit empty-set expert.

This construction yields:

1. **local failure robustness**, because reliability is estimated per object query and modality;
2. **an explicit no-observation state**, because the empty expert carries probability mass when all modalities are unreliable;
3. **calibration-aware fusion**, because state and extrinsic uncertainty determine local sampling support;
4. **temporal robustness**, because object hypotheses survive transient sensing failures without fabricated measurements;
5. **exact routing limits**, because routing excludes failed modalities and converges to the surviving-subset expert when surviving reliabilities also approach one;
6. **non-singular routing gradients**, because subset routing requires no normalization denominator;
7. **substantially better scaling**, because the multimodal fusion core replaces dense \(G^2\) interactions with query-local \(MQs\) interactions and query-level \(Q^2\) reasoning.

The result is a fusion architecture designed to degrade continuously and explicitly as sensing quality deteriorates, while keeping multimodal interaction sparse enough for real-time and edge-oriented deployment.

---

# References

[1] Xie et al., “SparseFusion: Fusing Multi-Modal Sparse Representations for Multi-Sensor 3D Object Detection,” ICCV 2023.  
https://openaccess.thecvf.com/content/ICCV2023/html/Xie_SparseFusion_Fusing_Multi-Modal_Sparse_Representations_for_Multi-Sensor_3D_Object_Detection_ICCV_2023_paper.html

[2] Sensoy, Kaplan, and Kandemir, “Evidential Deep Learning to Quantify Classification Uncertainty,” NeurIPS 2018.  
https://proceedings.neurips.cc/paper/2018/hash/a981f2b708044d6fb4a71a1463242520-Abstract.html

[3] “A Survey on Uncertainty Quantification Methods for Deep Learning,” ACM Computing Surveys.  
https://doi.org/10.1145/3786319
