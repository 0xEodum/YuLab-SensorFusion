# SF-06 surface heat and thermal IR

SF-06 implements a deterministic synthetic surface-heat model and an 8..14 um
long-wave infrared capture pass. It is intended for controlled research fixtures,
not as a calibrated signature model for the named equipment.

## Versioned thermal surfaces

Catalog records use `thermal-surface.v1`. Each imported part retains a semantic
exterior region and references an opaque IR material. The importer emits these
synthetic per-part coefficients:

| Region | Emissivity | Solar absorption | Capacity (J/K) | Area (m2) | Convection (W/(m2 K)) | Rated source (W) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| body | 0.82 | 0.55 | 250,000 | 4.0 | 8 | 0 |
| engine | 0.88 | 0.65 | 120,000 | 2.0 | 12 | 4,000 |
| exhaust | 0.92 | 0.70 | 60,000 | 1.0 | 20 | 12,000 |
| radiator | 0.94 | 0.75 | 100,000 | 1.5 | 16 | 2,500 |

Parts with the same semantic are one surface node. Area, heat capacity and rated
power sum; emissivity, absorption and convection are area-weighted. `WorldSpec`
instance state applies power fractions 0 / 0.25 / 1 for off / idle / running.
The catalog source state records the rated running source, while the immutable
world snapshot selects the actual operating state.

The aerodrome fixture runs the unobstructed F-16 and service vehicle, idles the
wide RQ-4 and partially occluded F-16, and leaves the hidden F-16 off. Internal
power is never rendered as visible source geometry. It heats only the named
exterior node, so the airframe and hangar geometry continue to occlude it.

## Fixed-step evolution and replay

`thermal-state.v1` stores simulation time, ambient temperature and sorted
instance/region temperatures. The implemented balance is:

`C dT/dt = Qsource + Qsolar - h A (T - Tair) - epsilon sigma A (T^4 - Tenv^4)`.

`equilibrated` captures solve the nonlinear equilibrium by bounded bisection.
`continued` captures validate a previously published JSON artifact by ID, byte
length and SHA-256, reject backward time, and advance with deterministic RK4
steps of at most 1 s. The full step is fixed at 1 s; only a final fractional step
is permitted. Saving, decoding and continuing a shutdown state produces the same
cooldown bytes as uninterrupted evolution in the pinned runtime.

Solar input is a synthetic 800 W/m2 maximum scaled by the upward component of
the declared sun direction. Zero sun still yields emitted thermal radiance;
the LWIR shader ignores every RGB light and visual material color.

## LWIR formation and artifacts

`lwir-8-14um.v1` integrates Planck spectral radiance over 8..14 um with a fixed
120-interval Simpson rule. The opaque gray-body surface value is:

`L = epsilon Bband(Tsurface) + (1 - epsilon) Bband(Tambient)`.

SF-06 deliberately uses atmospheric transmission 1 and path radiance 0. Weather
attenuation/path emission belongs to SF-08. A seeded, additive detector-noise
profile uses sigma 0.02 W/(m2 sr), clamps negative values to zero and saturates at
200 W/(m2 sr). The raw top-left raster is float32 `W/m2/sr`; validity and
saturation are separate boolean NPY arrays.

The display-only `iron-v1` preview uses a fixed 33.180159..265.121003 W/(m2 sr)
scale (blackbody radiance at 270..450 K). Palette mapping happens after raw
radiance formation and cannot modify the float32 artifact. Instance IDs and RGB
colors are not inputs to heat or radiance. The pass uses the calibrated IR camera,
the same resident geometry, and ordinary depth testing, so walls and airframes
occlude hotter surfaces.

An IR-requested successful job adds:

- `ir_preview_png`: display-only fixed-scale color preview;
- `ir_radiance_npy`: H x W little-endian float32 raw radiance;
- `ir_validity_npy` and `ir_saturation_npy`: H x W NPY boolean masks;
- `thermal_state_json`: replayable `thermal-state.v1` snapshot;
- `ir_calibration` in metadata/result: response, band, units, noise, saturation,
  thermal versions and preview declaration.

## Declared limits

- Coefficients and source powers are synthetic and uncalibrated; names do not
  imply measured F-16, RQ-4 or vehicle signatures.
- Nodes are isothermal semantic regions. There is no conduction between nodes,
  view-angle emissivity, transmission, multiple reflection or sub-pixel mixing.
- Terrain and structures use ambient temperature with emissivity 0.95. Detailed
  background heat, weather and time presets remain SF-08.
- The initial synchronized profile requires matching 640 x 384 RGB/IR raster
  dimensions. Sensor extrinsics remain distinct (IR baseline 0.35 m).
- Pinned renderer/device repeats are byte-identical in acceptance. GPU and
  SwiftShader raster edges can differ, so cross-device byte identity is not claimed.
- Browser GPU-allocation telemetry remains unavailable. The queue stays at one.

