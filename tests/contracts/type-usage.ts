// Compile-time regression: the code generator must preserve fixed-length matrices.
import type { Transform, Quaternion, Health } from '../../packages/contracts/src/generated.js';

export const identity: Transform = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
export const orientation: Quaternion = [0, 0, 0, 1];
export const health: Health = { schema_version: 'lab.v1', kind: 'Health', status: 'ok', service: 'yulab-backend', service_version: '0.1.0' };
// @ts-expect-error Missing homogeneous row cannot be a transform.
export const invalidTransform: Transform = [1, 0, 0];
// @ts-expect-error Unsupported schema versions are not valid payloads.
export const invalidHealth: Health = { ...health, schema_version: 'lab.v2' };
