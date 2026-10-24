import { mkdirSync, mkdtempSync, rmSync, lstatSync, existsSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const parent = fileURLToPath(new URL('../.runtime/tmp/', import.meta.url));

export function temporaryDirectory(t, prefix) {
  mkdirSync(parent, { recursive: true });
  if (lstatSync(parent).isSymbolicLink()) throw new Error('Scratch root must not be a link');
  const folder = mkdtempSync(join(parent, prefix.replace(/[^a-zA-Z0-9_-]/g, '-')));
  // Registered before builds/assertions so node:test also cleans failed tests.
  t.after(() => {
    if (!existsSync(folder)) return;
    if (dirname(resolve(folder)) !== resolve(parent) || lstatSync(folder).isSymbolicLink()) {
      throw new Error('Cleanup requires an owned direct child');
    }
    try {
      rmSync(folder, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    } catch {
      console.warn(`WARNING: could not remove acceptance directory: ${prefix}`);
    }
  });
  return folder;
}

// uv puts the venv interpreter under Scripts/ on Windows and bin/ elsewhere.
export function backendPython(root) {
  return process.platform === 'win32'
    ? join(root, 'backend/.venv/Scripts/python.exe')
    : join(root, 'backend/.venv/bin/python');
}
