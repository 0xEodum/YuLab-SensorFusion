# lab.v1 wire contracts

`lab.schema.json` is the canonical JSON Schema 2020-12 source for the ten lab
payload families in DATA_CONTRACTS plus Health, Capabilities and ApiError.
`openapi.json` is the canonical HTTP surface; it exposes only the two implemented
GET operations. Future operations in ARCHITECTURE are plans, not callable stubs.

Generated outputs (do not edit):

- `packages/contracts/src/generated.ts` and `index.ts`: TypeScript types/exports.
- `backend/app/generated.py`: Python TypedDict bindings.
- `openapi.bundle.json`: self-contained OpenAPI served by FastAPI.

Run `npm run contracts:generate` after an intentional contract edit and
`npm run contracts:check` in verification. Generators are pinned in the npm/uv
locks, omit timestamps, resolve allowlisted local references only, and write only
the named outputs (temporary files under ignored `artifacts/codegen`). The TS
generator receives an equivalent draft-07 tuple representation because its
native 2020-12 prefixItems support is incomplete. Runtime validation always uses
the original 2020-12 schema, including tuples and conditional constraints.

TypeScript's `validatePayload` and Python's `validate_payload` validate untrusted
values before use. Their strict JSON loaders also reject NaN, infinity and
overflowed numeric literals. Generated static types are not runtime validators;
they cannot by themselves enforce numeric bounds, matrix dimensions, hashes,
conditional sensor structures or absence of unknown fields.

Both runtime test suites consume the same examples and `fixtures/cases.json`.
Each case specifies either raw JSON or a base example plus `set`/`delete` changes
at an array of object keys/list indices. This keeps expected acceptance identical
across languages. Example assets/checkpoints are synthetic contract fixtures,
not imported models or working services. Never serve a fixture as capabilities.

The schemas validate wire structure and declared units/frames, not file contents
or physical correctness. Geometric calibration, rigid-transform orthogonality,
artifact resolution/hashes, actual masks/visibility and dataset leakage checks
still belong to their implementation stages. Their absence is not permission
to claim a captured dataset or trained model is validated in SF-01.

Provider and consumer ownership currently sit with this repository. Change the
canonical schema first, regenerate, review the diff and update both runtimes'
shared fixtures. Breaking changes require a new schema version and explicit
migration, never silent reinterpretation of `lab.v1`.
