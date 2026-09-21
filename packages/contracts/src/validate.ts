import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import schema from '../../../contracts/lab.schema.json' with { type: 'json' };
import type { LabPayload } from './generated.js';

const ajv = new Ajv2020({ allErrors: true, strict: false, strictNumbers: true });
addFormats(ajv);
ajv.addSchema(schema);
const validators = new Map<string, ReturnType<typeof ajv.compile>>();

function finite(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(finite);
  if (value && typeof value === 'object') return Object.values(value).every(finite);
  return true;
}

export function parseJson(text: string): unknown {
  const value: unknown = JSON.parse(text);
  if (!finite(value)) throw new Error('Non-finite JSON number');
  return value;
}

/** Wire validation is authoritative; generated types alone do not validate data. */
export function validatePayload<T extends LabPayload['kind']>(name: T, value: unknown): asserts value is Extract<LabPayload, { kind: T }> {
  if (!(name in schema.$defs) || !('properties' in schema.$defs[name])) throw new Error(`Unknown payload: ${name}`);
  if (!finite(value)) throw new Error('Non-finite number at payload boundary');
  let validator = validators.get(name);
  if (!validator) {
    validator = ajv.compile({ $ref: `${schema.$id}#/$defs/${name}` });
    validators.set(name, validator);
  }
  if (!validator(value)) throw new Error(ajv.errorsText(validator.errors, { dataVar: '$', separator: '; ' }));
}
