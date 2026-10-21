import { temporaryDirectory } from '../../scripts/runtime_tmp.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

test('React AI 備援欄位、版本、中文錯誤、移除背景輪詢與實際模型（HTTP mock）', { timeout: 120000 }, (t) => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const dist = temporaryDirectory(t, 'frontend-build-');
  const build = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', dist], { cwd: path.join(root, 'frontend'), encoding: 'utf8' });
  assert.equal(build.status, 0, build.stdout + build.stderr);
  const result = spawnSync(path.join(root, 'backend/.venv/Scripts/python.exe'), ['../scripts/check_ai_resilience_frontend.py'], {
    cwd: path.join(root, 'backend'), encoding: 'utf8', timeout: 100000,
    env: { ...process.env, PYTHONUTF8: '1', FRONTEND_DIST_DIR: dist },
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
