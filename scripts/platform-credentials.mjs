import { spawnSync } from 'node:child_process';
import { createDecipheriv, randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

// A one-use IPC key travels on stdin. Subprocess output contains only ciphertext,
// and neither raw errors nor environment credentials are printed.
export function readPlatformSettings(settings, run = spawnSync) {
  const key = randomBytes(32);
  try {
    const result = run('uv', ['run', 'python', '../scripts/platform_credentials.py'], {
      cwd: fileURLToPath(new URL('../backend', import.meta.url)),
      input: key.toString('base64'), encoding: 'utf8', windowsHide: true,
      timeout: 20000, maxBuffer: 128 * 1024,
    });
    if (result.status !== 0) throw new Error();
    const packed = Buffer.from(result.stdout.trim(), 'base64');
    const decipher = createDecipheriv('aes-256-gcm', key, packed.subarray(0, 12));
    decipher.setAAD(Buffer.from('platform-config'));
    decipher.setAuthTag(packed.subarray(-16));
    return { ...settings, ...JSON.parse(Buffer.concat([
      decipher.update(packed.subarray(12, -16)), decipher.final(),
    ]).toString('utf8')) };
  } catch {
    throw new Error('平台憑證無法讀取，請確認 migration 與加密主金鑰。');
  } finally { key.fill(0); }
}
