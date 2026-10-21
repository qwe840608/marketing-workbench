import { temporaryDirectory } from '../../scripts/runtime_tmp.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

test('React 單篇留言抓取：權限、排隊、等待、完成、停止及 7／30／90 篩選（HTTP mock）', { timeout: 120000 }, (t) => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const dist = temporaryDirectory(t, 'frontend-build-');
  const build = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', dist], {
    cwd: path.join(root, 'frontend'), encoding: 'utf8',
  });
  assert.equal(build.status, 0, build.stdout + build.stderr);
  const result = spawnSync(path.join(root, 'backend/.venv/Scripts/python.exe'), ['../scripts/check_comment_sync_frontend.py'], {
    cwd: path.join(root, 'backend'), encoding: 'utf8', timeout: 100000,
    env: { ...process.env, PYTHONUTF8: '1', FRONTEND_DIST_DIR: dist },
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
