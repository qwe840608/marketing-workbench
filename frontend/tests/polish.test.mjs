import { temporaryDirectory } from '../../scripts/runtime_tmp.mjs';
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../../', import.meta.url));
const dist = temporaryDirectory({ after }, 'frontend-build-');
// check_polish_frontend 也涵蓋四項導覽與已移除收件匣（原 ui_inbox_layout／ui_composer）。
test('React 接收健康狀態可見頁面輪詢（HTTP mock、桌面及手機）', { timeout: 240000 }, () => {
  const build = spawnSync(process.execPath, ['node_modules/typescript/bin/tsc', '--noEmit'], { cwd: path.join(root, 'frontend'), encoding: 'utf8' });
  assert.equal(build.status, 0, build.stdout + build.stderr);
  const bundle = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', dist], { cwd: path.join(root, 'frontend'), encoding: 'utf8' });
  assert.equal(bundle.status, 0, bundle.stdout + bundle.stderr);
  const result = spawnSync(path.join(root, 'backend/.venv/Scripts/python.exe'), ['../scripts/check_polish_frontend.py'], {
    cwd: path.join(root, 'backend'), encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1', FRONTEND_DIST_DIR: dist }, timeout: 220000,
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
