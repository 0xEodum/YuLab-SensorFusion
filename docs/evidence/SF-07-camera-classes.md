# SF-07 camera view and class reference follow-up

Date: 2026-09-23. This follow-up leaves the first-return beam geometry and
raw response contract intact. The main LiDAR preview now projects returns into
the calibrated saved RGB camera, using a per-pixel nearest-point depth test.
The overhead sensor-frame plot is a secondary artifact. Both color each point
by a stable `lidar-semantic.v1` simulator class; the UI shows the class legend.

The new `lidar_class_ref_npy` is an N-element uint8 reference array in exactly
the sparse XYZ/beam order. `lidar_ideal_class_npy` is a rows-by-columns uint8
pre-response first-hit table. Class 0 means unclassified on a hit and no
surface on a no-return beam; `lidar_beam_status_npy` disambiguates them.
Receiver dropout publishes no sparse point but retains the ideal class.
Neither class array is a measured LiDAR channel or model inference input.
Class names, IDs and display colors are in calibration metadata and
[the LiDAR profile](../LIDAR.md).

## Visual and raw evidence

| Camera perspective | Secondary top-down | Full capture |
| --- | --- | --- |
| [Class-colored camera view](sf07-camera-classes/lidar-camera.png) | [Class-colored overhead view](sf07-camera-classes/lidar-topdown.png) | [Desktop](sf07-camera-classes/capture-desktop.png) / [mobile](sf07-camera-classes/capture-mobile.png) |

The two 640 x 384 LiDAR images and desktop capture were inspected. The F-16
appears in the camera-aligned cloud, while the original arcs remain visible in
the separate overhead plot. The [capture result](sf07-camera-classes/capture-metadata.json)
records 20,627 sparse returns: 359 terrain, 19,716 pavement, 51 marking and
501 aircraft. It records the class reference SHA-256 as
`05518505aaad4dac17b8f32bdceb454585d2213c1190778c7e63842e94dc623c`.
The XYZ and beam-status hashes exactly match the prior SF-07 example, which
supports that this follow-up changed labels and presentation rather than the
scan geometry or response for this pinned capture. The renderer was local
Edge Chromium 153 with SwiftShader; cross-renderer PNG equality is not claimed.

## Verification

- The new first-hit fixture failed before the class implementation, then
  passed after it. It covers a front building, a partly visible aircraft,
  sparse/ideal class alignment and receiver dropout.
- `npm run verify` passed after the final source changes: generated contracts,
  TypeScript checks, 65 contract, 19 world, 24 sensor, 4 asset and 81 backend
  tests, and the production build.
- Production-built Edge capture acceptance passed 1/1 after the final preview
  dimension adjustment. It checks seven synchronized panes, NPY lengths and
  class alignment, visible aircraft and pavement colors, and distinct camera
  and top-down PNGs.
- The full production Edge browser suite passed 16/16 before the final
  top-down viewport-size, projection-metadata and historical-result
  compatibility adjustments. The final changes passed `npm run verify` and
  the focused capture run. The suite also revealed
  an existing wait that could
  accept the previous chunk's ready state; its 104-crossing test passed after
  waiting for the requested identity, residency keys and readiness together.
- An older SF-07 capture fixture still validates as a completed job after the
  new calibration fields were made optional for historical results. New jobs
  publish the fields and artifacts through the capture-worker gate.

SF-08 remains the next READY backlog item. Weather-conditioned returns and
sensor response are outside this follow-up.
