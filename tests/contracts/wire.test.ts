import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validatePayload, parseJson } from '../../packages/contracts/src/validate.ts';
import type { LabPayload } from '../../packages/contracts/src/generated.js';

type Case = { name: string; schema: LabPayload['kind']; valid: boolean; raw?: string; base?: string; patches?: { op: 'set' | 'delete'; path: (string | number)[]; value: unknown }[] };
const dir = new URL('../../contracts/fixtures/', import.meta.url);
const cases: Case[] = JSON.parse(readFileSync(new URL('cases.json', dir), 'utf8'));

for (const fixture of cases) {
  test(fixture.name, () => {
    const run = () => {
      const value = parseJson(fixture.raw ?? readFileSync(new URL(fixture.base!, dir), 'utf8'));
      for (const patch of fixture.patches ?? []) {
        let target = value as Record<string, unknown>;
        for (const key of patch.path.slice(0, -1)) target = target[key] as Record<string, unknown>;
        const key = patch.path.at(-1)!;
        if (patch.op === 'delete') delete target[key];
        else target[key] = patch.value;
      }
      validatePayload(fixture.schema, value);
    };
    if (fixture.valid) assert.doesNotThrow(run);
    else assert.throws(run);
  });
}

test('in-memory non-finite numbers cannot bypass JSON parsing', () => {
  for (const invalid of [NaN, Infinity, -Infinity]) {
    const world = JSON.parse(readFileSync(new URL('WorldSpec.json', dir), 'utf8'));
    world.extent_m[0] = invalid;
    assert.throws(() => validatePayload('WorldSpec', world), /Non-finite/);
  }
});

test('every public family has a positive fixture', () => {
  const schema = JSON.parse(readFileSync(new URL('../../contracts/lab.schema.json', import.meta.url), 'utf8'));
  const names = schema.oneOf.map((r: { $ref: string }) => r.$ref.split('/').at(-1));
  assert.deepEqual(new Set(cases.filter(c => c.valid).map(c => c.schema)), new Set(names));
});
