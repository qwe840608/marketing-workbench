import { backendPython, temporaryDirectory } from '../../scripts/runtime_tmp.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// verify_all 會直接跑 check_dm_backfill_frontend.py（同一份前端原始碼建置），這裡不再重建、重跑一次。
const alreadyRun = process.env.VERIFY_ALL_RUNS_BROWSER_CHECKS === '1' && 'verify_all 已直接執行 check_dm_backfill_frontend';

test('React 私訊回補：全部歷史、90 天、個別帳號重新補抓與平台限制（HTTP mock）', { timeout: 120000, skip: alreadyRun }, (t) => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const dist = temporaryDirectory(t, 'frontend-build-');
  const bundle = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', dist], { cwd: path.join(root, 'frontend'), encoding: 'utf8' });
  assert.equal(bundle.status, 0, bundle.stdout + bundle.stderr);
  const result = spawnSync(backendPython(root), ['../scripts/check_dm_backfill_frontend.py'], {
    cwd: path.join(root, 'backend'), encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1', FRONTEND_DIST_DIR: dist }, timeout: 100000,
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
