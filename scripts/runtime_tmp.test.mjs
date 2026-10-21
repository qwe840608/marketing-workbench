import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

test('node:test releases its build directory after success and assertion failure', () => {
  for (const fail of [false, true]) {
    const source = `
      import test from 'node:test';
      import { writeFileSync, chmodSync } from 'node:fs';
      import { join } from 'node:path';
      import { temporaryDirectory } from ${JSON.stringify(new URL('./runtime_tmp.mjs', import.meta.url).href)};
      test('owned build', t => {
        const folder = temporaryDirectory(t, 'node-clean-unit-');
        console.log('SCRATCH=' + folder);
        writeFileSync(join(folder, 'index.html'), 'isolated');
        chmodSync(join(folder, 'index.html'), 0o444);
        if (${fail}) throw new Error('intentional failure');
      });
    `;
    const result = spawnSync(process.execPath, ['--input-type=module', '--eval', source], { encoding: 'utf8' });
    assert.equal(result.status, fail ? 1 : 0, result.stderr);
    const folder = result.stdout.match(/SCRATCH=(.+)/)?.[1].trim();
    assert.ok(folder, result.stdout);
    assert.equal(existsSync(folder), false, folder);
  }
});
