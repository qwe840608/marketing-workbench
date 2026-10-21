import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
// check_runtime_polish.ps1 依賴 Windows PowerShell；其他平台沒有 powershell.exe，略過而非失敗。
test('PowerShell 停止競態、PID 重用、權限錯誤（完全替身）', { skip: process.platform !== 'win32' && '需要 Windows PowerShell' }, () => {
  const result = spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', fileURLToPath(new URL('./check_runtime_polish.ps1', import.meta.url))], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /4 passed/);
});
