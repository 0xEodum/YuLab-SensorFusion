# RQ-4 parked model correction

The supplied `aircraft/rq-4-uav` source is outside this repository. The
checked-in `tools/assets/rq4-corrections.mjs` applies four anchored import
changes: orient the intake lip in the vertical XY plane, extend the nose leg
into the belly, extend both main legs to the wing underside, and add diagonal
main gear trunnions that enter the fuselage. An upstream source change that
invalidates an anchor fails import instead of silently dropping a correction.

Rebuild with `npm run assets:import -- "K:\PycharmProjects\world_models\Generated"`.
The RQ-4 `AssetRecord` carries adapter version
`static-model.rq4-corrections.v1`; the external source-file SHA-256 values are
unchanged. The imported GLB is 596,924 bytes and contains 2,376 triangles in
73 meshes. Bounds remain 39.920 × 4.496 × 15.100 m and tyre contacts remain
within the existing 15 mm placement tolerance.

`npm run test:assets` passed (6/6) and `npm run typecheck` passed. Edge on an
RTX 3090 rendered the [close RQ-4 view](rq4-corrections.png) with no page
errors. From this front-quarter pose, the intake rim is upright and the main
gear braces meet the fuselage. The nose leg enters the belly behind the doors.
