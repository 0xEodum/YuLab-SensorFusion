# SF-07 first-return LiDAR profile

The saved rig defines a separate LiDAR pose. The sensor frame is +X forward,
+Y left, +Z up; `T_world_from_rig * T_rig_from_sensor` maps that frame into
world metres. A saved Three.js camera points along -Z, so its LiDAR +X maps
to that direction. The RGB, IR and LiDAR origins need not coincide.

## Beam and geometry policy

`lidar-first-return.v1` emits a row-major `rows * columns` grid. Column 0 is
the left edge of the horizontal field, the final column is the right edge;
row 0 is the top edge of the vertical field. For a one-row or one-column
pattern, the sole angle is zero. Each beam records a stable ID and
`timestamp_offset_s + scan_duration_s * beam_id / (beam_count - 1)` (zero
scan fraction for a single beam). The v1 capture scene is frozen at the plan
tick; a nonzero scan duration declares acquisition timestamps without motion
interpolation. Moving-scene/rolling capture belongs to SF-13.

The worker constructs the same 2 m sensor-resident terrain, decorations,
aerodrome structures and catalog meshes used by RGB and IR. It unions the
conservative RGB and LiDAR range leases before capture. Editor helpers never
enter the scan. Catalog surfaces with `opaque_lidar=false` are excluded.
LiDAR queries two levels of acceleration: a mesh BVH for triangles and a
scene BVH over mesh bounds. Both operate on the actual triangles. The
brute-force Three.js raycast is retained in fixed-fixture tests as a
correctness reference. No mesh-vertex sampling, full-scene point cloud, or
RGB depth reuse is involved.

The nearest opaque triangle within inclusive min/max range is selected before
receiver response. Both faces of a thin opaque triangle are hittable; a ray
inside a closed solid sees its exit face. Equal-range ties within 1 nm choose
the earlier mesh in deterministic scene traversal; within that mesh the pinned
BVH build order resolves a triangle-edge tie.
This is a geometric policy for synthetic assets, not a model of transmissive
or refractive material.

## Response and output

The v1 synthetic intensity uses `0.65 * max(0.02, |normal dot beam|) *
exp(-range_m / 200)`. A seeded receiver adds independent Gaussian intensity
noise with sigma 0.01 and Gaussian range noise with sigma 0.003 m. Range is
clamped to the calibrated sensor interval. Default clear-scene receiver
dropout probability is zero; tests may set it to one. Dropout changes a
first-surface beam to status 2 and **never searches farther geometry**.
Atmospheric attenuation, particles and weather-conditioned noise belong to
SF-08. These numerical coefficients are synthetic and uncalibrated.

The sparse observation arrays use NPY, little-endian data in sensor metres:

| Artifact | Shape and type | Meaning |
| --- | --- | --- |
| `lidar_xyz_npy` | N x 3 float32 | Detected surface XYZ in LiDAR frame |
| `lidar_intensity_npy` | N float32 | Unit-interval synthetic response |
| `lidar_beam_id_npy` | N uint32 | Original row-major beam ID |
| `lidar_time_offset_npy` | N float32 | Seconds from frozen capture tick |
| `lidar_validity_npy` | N bool | One for each published point |
| `lidar_class_ref_npy` | N uint8 | Simulator reference class aligned one-to-one with published XYZ, not a sensor measurement |
| `lidar_beam_status_npy` | rows x columns uint8 | 0 no return, 1 surface, 2 receiver dropout |
| `lidar_ideal_range_npy` | rows x columns float32 | Pre-response nearest range; zero for no surface |
| `lidar_ideal_instance_npy` | rows x columns uint32 | Pre-response stable instance ID; zero for background |
| `lidar_ideal_class_npy` | rows x columns uint8 | Pre-response first-hit class; zero for no surface or unclassified |

`lidar-semantic.v1` assigns stable class IDs: 0 unclassified, 1 terrain,
2 pavement, 3 marking, 4 building, 5 vegetation, 6 rock, 7 fence,
8 aircraft, 9 ground vehicle, 10 ship, 11 water. The calibration metadata
includes the ID, name and display color table. An `AssetRecord` class supplies
catalog-object labels; terrain, placements and aerodrome structures supply
their own surface labels. An asset with only the generic `background` class is
unclassified. No-return and unclassified hits both have class 0 in the ideal
class table; the beam-status table distinguishes them. Receiver dropout keeps
the ideal class but publishes no sparse point. These class arrays are reference
truth for labeling and evaluation; a model's LiDAR observation is XYZ,
intensity, beam ID, time, validity and status without class input.

`lidar_range_preview_png` visualizes the beam grid with a fixed logarithmic
0..max-range display scale. `lidar_cloud_preview_png` projects sparse returns
through the calibrated RGB camera at the saved rig pose, with nearest-point
depth ordering and semantic class colors. `lidar_topdown_preview_png` is the
secondary plot from above in the LiDAR sensor frame. The class legend in the
capture UI uses the calibration table. Calibration metadata names both preview
projections explicitly. All three PNGs are display only.
Older completed jobs without class metadata remain valid; new captures always
publish the class table and both projection names.
`metadata_json` records the pattern, FOV, timing, ranges, extrinsics, response,
point count and file hashes. An empty valid scan has N=0 and a full beam table
of no-return statuses. The ideal arrays are reference truth and must not be
fed into an inference input; SF-10 will package observation and truth bundles.

## Limits

The v1 ray/triangle tests use discrete angular beams and a static scene.
Return intensity is a simple incidence/range proxy, not a measured
reflectance or laser-power calibration. The worker remains a
single-host, one-job queue with a 120 s limit. GPU memory telemetry is still
unavailable; the LiDAR BVH runs on CPU in the capture browser.
