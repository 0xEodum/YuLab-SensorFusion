import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
export function runUv(args) {
  const local = resolve(root, '.tools', process.platform === 'win32' ? 'Scripts/uv.exe' : 'bin/uv');
  const result = spawnSync(existsSync(local) ? local : 'uv', args, { cwd: root, stdio: 'inherit' });
  if (result.error) throw new Error('uv is unavailable. Follow README.md to bootstrap .tools or install uv 0.12.17.', { cause: result.error });
  if (result.status !== 0) throw new Error(`uv exited with ${result.status}`);
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runUv(process.argv.slice(2));
}
