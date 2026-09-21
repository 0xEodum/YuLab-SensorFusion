import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { compile } from 'json-schema-to-typescript';
import { runUv, root } from './uv.mjs';

const schema = JSON.parse(await readFile(resolve(root, 'contracts/lab.schema.json'), 'utf8'));
const api = JSON.parse(await readFile(resolve(root, 'contracts/openapi.json'), 'utf8'));
// Refuse remote/file retrieval: all definitions are local and explicitly allowlisted.
function rewrite(value, apiMode = false) {
  if (Array.isArray(value)) return value.map(v => rewrite(v, apiMode));
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).map(([k, v]) => {
    if (k !== '$ref') return [k, rewrite(v, apiMode)];
    const prefix = apiMode ? './lab.schema.json#/$defs/' : '#/$defs/';
    if (!v.startsWith(prefix) || !(v.slice(prefix.length) in schema.$defs)) throw new Error(`Untrusted schema reference: ${v}`);
    return [k, '#/components/schemas/' + v.slice(prefix.length)];
  }));
}
rewrite(schema); // Validate before passing anything to generators.
const bundle = rewrite(api, true);
bundle.components.schemas = Object.fromEntries(Object.entries(schema.$defs).map(([k, v]) => [k, rewrite(v)]));
const staging = resolve(root, 'artifacts/codegen');
await mkdir(staging, { recursive: true });
// The TS generator expects draft-07 tuple syntax; preserve 2020-12 tuple meaning.
// This adaptation is only for static types. Both runtimes validate the original.
function forTypes(value) {
  if (Array.isArray(value)) return value.map(forTypes);
  if (!value || typeof value !== 'object') return value;
  const adapted = Object.fromEntries(Object.entries(value).map(([k, v]) => [k, forTypes(v)]));
  if (adapted.prefixItems) {
    adapted.additionalItems = adapted.items;
    adapted.items = adapted.prefixItems;
    delete adapted.prefixItems;
  }
  return adapted;
}
const ts = await compile(forTypes(schema), 'LabPayload', {
  bannerComment: '/* Generated from contracts/lab.schema.json. Do not edit. */',
  unreachableDefinitions: true,
  maxItems: 20,
});
const names = Object.keys(schema.$defs).filter(k => schema.$defs[k].properties?.kind);
const exports = names.map(name => `export { type ${name} } from './generated.js';`).join('\n');
runUv(['run', '--project', 'backend', '--locked', 'datamodel-codegen',
  '--input', 'contracts/lab.schema.json', '--input-file-type', 'jsonschema',
  '--output', 'artifacts/codegen/generated.py', '--output-model-type', 'typing.TypedDict',
  '--target-python-version', '3.13', '--disable-timestamp', '--use-union-operator',
  '--no-use-closed-typed-dict', '--formatters', 'black', 'isort']);
const python = await readFile(resolve(staging, 'generated.py'), 'utf8');
const outputs = {
  'packages/contracts/src/generated.ts': ts,
  'packages/contracts/src/index.ts': `/* Generated public payload types. */\n${exports}\nexport type PayloadName = ${names.map(n => `'${n}'`).join(' | ')};\nexport { validatePayload, parseJson } from './validate.js';\n`,
  'backend/app/generated.py': python,
  'contracts/openapi.bundle.json': JSON.stringify(bundle, null, 2) + '\n',
};
for (const [path, text] of Object.entries(outputs)) {
  const dest = resolve(root, path);
  const normalized = text.replaceAll('\r\n', '\n');
  if (process.argv.includes('--check')) {
    const current = await readFile(dest, 'utf8');
    if (current.replaceAll('\r\n', '\n') !== normalized) throw new Error(`Generated file is stale: ${path}`);
  } else {
    await mkdir(resolve(dest, '..'), { recursive: true });
    await writeFile(dest, normalized);
  }
}
console.log(`Contract generation ${process.argv.includes('--check') ? 'verified' : 'complete'} (${names.length} payload types).`);
