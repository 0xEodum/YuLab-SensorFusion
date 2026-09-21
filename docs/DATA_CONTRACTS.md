# World, observation and annotation contracts

Status: `lab.v1` wire foundation implemented in SF-01. Canonical
[JSON Schema](../contracts/lab.schema.json) and [OpenAPI](../contracts/openapi.json)
define payload validation and generated language bindings. Shared fixtures cover
all ten payload families and the three foundation API envelopes in both runtimes.
This prose defines data/physical semantics for the later capture and dataset
stages; schema-valid metadata alone does not prove correct geometry, sensor
simulation, file contents or labels. See [contract guidance](../contracts/README.md).

## 1. Coordinate, time and identity conventions

- World/rig: right-handed, metres, +X east, +Y up, +Z south. Sun direction and wind
  use this same basis; local geographic origin/latitude are explicit metadata.
- Optical camera: +X right, +Y down, +Z forward. LiDAR: +X forward, +Y left, +Z up.
  Conversion to the Three.js camera frame is explicit and fixture-tested.
- `T_A_from_B` transforms a column vector in B into A. Serialized 4x4 matrices
  are row-major. Do not serialize Three.js column-major storage without conversion.
- Image origin is top-left; pixel centers are `(u+0.5,v+0.5)`. Intrinsics are in
  pixels. Distortion parameters are explicit; ideal pinhole is a named profile.
- Angles are radians, temperature Kelvin, time seconds from sequence start;
  UI Celsius/hours conversions are presentation only. Wall-clock UTC is provenance.
- A 3D box has center, positive XYZ extents and quaternion `[x,y,z,w]` in the
  declared frame. ESSRF's yaw-only head is an explicit restricted profile.
- Stable string IDs identify worlds, assets, instances, sequences, captures and
  artifacts. They do not depend on array order or which chunks are resident.
- Deterministic random streams derive from world seed, sequence/capture ID,
  modality and purpose. Weather noise must not perturb object placement RNG.
- Schema, generator, sensor model, class map and thermal model have separate
  versions. Unsupported versions fail explicitly; migrations preserve originals.

## 2. Authoritative payload families

SF-02R consumes the existing `WorldSpec` shape with generator version
`connected-world.v2` and field version `connected-field.v2`. The
[supported profile](WORLD_GENERATOR.md) adds semantic bounds, unique feature IDs,
immutable snapshot behavior, supported feature types and meshing/placement
policy. Wire-valid future versions or asset instances are not silently accepted
by this generator. Biomes are world-space fields owned by the field version.
No wire-schema change is needed.

| Payload | Required content | Permitted consumers |
| --- | --- | --- |
| `AssetRecord` | ID, content hash, source provenance, units/axes, mesh/sidecar references, subpart and thermal/material definitions | World builder, capture, catalog UI |
| `WorldSpec` | Seed, extent, chunk/field versions, feature layout, instance asset references/transforms/states | World builder, capture, editor |
| `RigSpec` | Per-sensor intrinsics/extrinsics, calibration version, timing, availability, range/resolution/beam pattern | Capture, training, inference |
| `EnvironmentSpec` | Clock, illumination, temperature, fog/rain/snow/wind/wetness, parameter-set versions | Capture and experiment UI only |
| `CapturePlan` | World/rig/environment hashes, simulation time, fixed quality, seed channels, requested modalities | Job coordinator, capture |
| `ObservationBundle` | Capture/sequence ID, raw file references/hashes, shapes/dtypes/units, sensor timestamps, nominal calibration, validity and health | Training and inference |
| `AnnotationBundle` | Instance/class IDs, visible masks/boxes/counts, geometric visibility, eligible targets, ignore reasons, 3D boxes | Training/evaluation and separate truth overlay |
| `TruthBundle` | Full object states, exact poses/calibration, clean sensor intermediates, corruption masks and thermal state | Simulation debugging and supervision construction only |
| `DatasetManifest` | Immutable file hashes, capture IDs, generation provenance, disjoint split group IDs, class map and summary counts | Validation, training, evaluation |
| `PredictionBundle` | Capture/checkpoint ID, predicted class/box/score/uncertainty, measured latency, optional routing/state | Demo and evaluation |

Inference rejects unknown truth-bearing fields. It cannot open dataset label
directories or resolve a capture ID into world state. A prediction object cannot
carry a truth instance ID; evaluation performs matching separately. Calibration
drift experiments supply nominal calibration to the detector and retain exact
transforms only in truth. Environmental settings are not model reliability inputs.

Machine schemas must define finite-value/range checks, bounded array sizes,
nullable fields, enums, coordinate frames, and field-specific errors. API errors
use a stable code, message, request/job ID and structured field details. A missing
modality is explicit (`unavailable`, reason), not silently synthesized or replaced.

## 3. Sensor observations

| Modality | Raw data | Distinct preview/derived data |
| --- | --- | --- |
| RGB | HxWx3 uint8 sensor-output RGB, declared transfer function/exposure, valid-pixel mask; optional linear reference under truth | Display tone mapping and browser thumbnail |
| IR | HxW float32 band-integrated calibrated radiance, validity/saturation masks, band and response metadata; optional quantized DN plus conversion | Fixed-scale or declared auto-scale color map |
| LiDAR | Nx3 float32 XYZ in sensor frame, intensity, beam ID, time offset, validity; beam table including no-return status | Range/depth projection and point-cloud display |

Initial pilot proposal: 640x384 RGB/IR, 64x512 LiDAR angular samples, 250 m
maximum range. Resolutions, FOVs, min range and scan timing are rig parameters,
not implicit constants. Larger worlds do not imply infinite sensor range.
Co-located fixture projections must agree to <=0.5 pixel away from raster edges.

Images retain dimensions and an explicit invalid-value policy; numeric NaNs are
not serialized in JSON. Binary invalid values use a validity mask. Failed frames
are absent from completed manifests. Completely empty but valid LiDAR scans are
allowed and must be distinguished from failed capture or unavailable hardware.

## 4. Visibility and labels

At a frozen world time, render an integer instance-ID and depth pass from EACH
camera using all opaque occluders, including background terrain/buildings/trees.
Use nearest sampling, no antialiasing, no lighting, no fog, no blending and no tone
mapping in this ground-truth pass. Preserve alpha-test cutouts where the physical
geometry policy declares them. Reserve 0 for background and define ID capacity;
test ID encode/decode exactly rather than relying on display colors.

For instance i in camera m:

1. `visible_mask[i,m]` is the set of pixels where i wins the depth test.
2. `visible_box_xyxy[i,m]` is its tight half-open pixel rectangle; it is null if
   the mask is empty. Never annotate the projection of a full 3D box as a visible box.
3. `isolated_projected_pixels[i,m]` is the object's own raster silhouette in the
   same frustum with other occluders removed (self-occlusion retained).
4. `visible_fraction = visible_pixels / isolated_projected_pixels` when the
   denominator is nonzero; otherwise null/out-of-view. This is occlusion within
   the frame, not the fraction of the entire object outside the frustum.
5. Record `truncated` separately using frustum intersection. Keep amodal geometry
   bounds separate from visible masks and boxes.

For each LiDAR beam compute the nearest opaque intersection along its emitted
ray, before receiver dropout. Keep ideal hit instance/range in truth. Observation
points contain only detected surface or atmospheric returns. Store surviving
surface-hit counts per instance in annotations, plus separate ideal counts.
Atmospheric returns have no object instance label. Measurement noise may perturb
a surface range; it must not convert that return to a hidden object's identity.

Semantic geometry is shared across modalities, but visible masks are not reused
across distinct viewpoints. Motion/rolling scans later evaluate poses at each
sensor's sample time; simply copying a central-time mask is not acceptable.

**Geometric visibility is different from detectability.** Fog, low illumination,
thermal crossover, sparse beams and sensor corruption may remove useful signal
without changing opaque occlusion. Store geometric labels and separate
sensor-support/corruption metadata; do not erase hard examples because a model
cannot detect them. Learned confidence is never annotation ground truth.

Initial observable-object detection policy:

- Object is eligible if it has at least 16 visible geometric pixels in either
  camera OR 3 ideal geometric LiDAR hits. The thresholds are versioned pilot
  policy values and will be sensitivity-tested before dataset freeze.
- Keep eligible objects as targets through adverse-weather corruption, including
  sensor dropout; evaluate abstention/failure separately from visibility.
- Fully geometrically occluded/out-of-frustum objects are not positive current-
  frame discovery targets. Record them in truth and ignore-policy metadata.
- Temporal continuation of a previously seen hidden object is a distinct task
  with persistence/horizon metrics, not a new current-frame detection.
- Smaller visible fragments are retained with an explicit ignore reason, not
  silently converted into background negatives. Evaluate 3D boxes as amodal
  extents of eligible objects; they do not shrink with occlusion.

Evaluation must implement these exact ignore and eligibility rules, including
how predictions matching ignored fragments are removed before scoring. Do not
ignore arbitrary false positives in empty space near hidden objects.

## 5. Thermal and weather semantics

V1 proposed surface-node energy balance:

`C * dT/dt = Q_source + Q_solar - h*A*(T-T_air) - epsilon*sigma*A*(T^4-T_env^4)`.

Here C is thermal capacity (J/K), Q terms are watts, h is W/(m² K), A is m²,
epsilon is dimensionless and sigma is the Stefan-Boltzmann constant. Parameters
are per material/source, integration uses a fixed recorded timestep, and
numerical stability/energy direction must be tested. Internal engine power
reaches modeled exterior surface nodes through an explicit coupling model;
it is not directly visible through the enclosing body.

Proposed sensor radiance:

`L = tau(d) * [epsilon * B_band(T) + (1-epsilon) * L_reflected] + L_path`.

`B_band` integrates blackbody radiance over the declared LWIR response band,
initially 8..14 micrometres; units are W/(m² sr) after band integration. The v1
gray-body approximation assumes band-constant emissivity. Response/noise,
clipping and quantization follow radiance formation. UI normalization is excluded
from the training input unless explicitly declared as a preprocessing variant.

The separation of emitted, reflected and atmospheric radiance follows the
measurement components described in [FLIR's thermographic measurement
guidance](https://support.flir.com/docdownload/assets/web/2p5q/en-us/T505000.xml.html).
Our proposed numerical coefficients and simplified heat dynamics still require
their own calibration; the reference does not validate the simulator.

Attenuation uses `tau(d)=exp(-beta*d)` with beta in m^-1, with separate spectral
coefficients for RGB, LWIR and LiDAR. LiDAR surface-return attenuation uses the
round trip. Fog/rain/snow presets select documented coefficient distributions;
their numeric mapping to real weather remains uncalibrated until measured.

LiDAR procedure: choose the first opaque surface; simulate atmosphere before
that distance; select the declared single-return response; apply receiver noise
and threshold. Never retry against a farther solid when the first surface return
drops. Range noise and particle returns are distinguishable in truth only.

Controlled tests must show: emissivity/temperature affect IR, off-state sources
cool, IR works without RGB illumination, night reduces RGB SNR under fixed
exposure, increased extinction reduces ensemble surface-return rate/contrast,
and a background temperature approaching object surface temperature reduces
thermal contrast. These are sensor tests, not guaranteed detector rankings.

## 6. Dataset integrity and replay

Store `observations/`, `annotations/`, and restricted `truth/` separately, indexed
by immutable capture IDs. Sensor files and labels are committed atomically as a
capture. The manifest includes every file's SHA-256, dimensions, dtype, units,
calibration, world/assets/config hashes, source revision and toolchain fingerprint.
Retain sensor model/preprocessing versions in checkpoints as well.

Training input assembly accepts only ObservationBundle fields. A contract test
replaces truth/labels with inaccessible or poisoned data and verifies inference
still works identically. Training labels are read only by loss/matching code,
not proposal construction, feature extraction or reliability inference.

Split groups encompass layout/world seed, trajectory and all derived condition
variants. Detect cross-split duplicate content and overlapping group IDs before
training. Validation chooses settings; sealed test evaluation happens after
selection. Dataset expansion creates a new version and preserves split rules.

Pinned-environment replay requires identical manifests and labels for exact
fixtures. Numeric renderer outputs need declared tolerances if the renderer
cannot guarantee bit identity; report deviations, never silently update hashes.
Archive the original completed artifacts for reproducible training comparisons.
