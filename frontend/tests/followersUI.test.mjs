import { backendPython, temporaryDirectory } from '../../scripts/runtime_tmp.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// verify_all 會直接跑 check_followers_frontend.py（同一份前端原始碼建置），這裡不再重建、重跑一次。
const alreadyRun = process.env.VERIFY_ALL_RUNS_BROWSER_CHECKS === '1' && 'verify_all 已直接執行 check_followers_frontend';

test('React 粉絲數：平台切換、預設年月週、歷史標籤與數值、無資料及兩列（HTTP mock）', { timeout: 120000, skip: alreadyRun }, (t) => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const dist = temporaryDirectory(t, 'frontend-build-');
  const build = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', dist], {
    cwd: path.join(root, 'frontend'), encoding: 'utf8',
  });
  assert.equal(build.status, 0, build.stdout + build.stderr);
  const result = spawnSync(backendPython(root), ['../scripts/check_followers_frontend.py'], {
    cwd: path.join(root, 'backend'), encoding: 'utf8', timeout: 100000,
    env: { ...process.env, PYTHONUTF8: '1', FRONTEND_DIST_DIR: dist },
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
