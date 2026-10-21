import test from 'node:test';
import assert from 'node:assert/strict';
import { pollWhileVisible } from '../src/visiblePolling.ts';

function fixture(t, visible = true) {
  const doc = new EventTarget(); doc.visibilityState = visible ? 'visible' : 'hidden';
  const timers = new Map(); let serial = 1;
  globalThis.document = doc;
  globalThis.window = { setInterval(fn) { const id=serial++; timers.set(id,fn); return id; }, clearInterval(id) { timers.delete(id); } };
  t.after(() => { delete globalThis.document; delete globalThis.window; });
  return { timers, visibility(value) { doc.visibilityState=value; doc.dispatchEvent(new Event('visibilitychange')); } };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
test('初始隱藏不請求，恢復立即一次，清理後不再請求', async t => {
  const f = fixture(t, false); let calls = 0;
  const stop = pollWhileVisible(async () => { calls++; }, 3000);
  assert.equal(calls, 0); assert.equal(f.timers.size, 0);
  f.visibility('visible'); await settle(); assert.equal(calls, 1); assert.equal(f.timers.size, 1);
  stop(); f.visibility('visible'); assert.equal(calls, 1); assert.equal(f.timers.size, 0);
});
test('隱藏取消進行中請求，重新可見使用新 signal 且舊回應不能寫入', async t => {
  const f = fixture(t); const signals = []; const complete = []; let applied = 0;
  const stop = pollWhileVisible(async signal => { signals.push(signal); await new Promise(resolve => complete.push(resolve)); if (!signal.aborted) applied++; }, 3000);
  f.visibility('hidden'); assert.ok(signals[0].aborted); assert.equal(f.timers.size, 0);
  f.visibility('visible'); assert.equal(signals.length, 2); assert.equal(signals[1].aborted, false);
  complete[0](); await settle(); assert.equal(applied, 0);
  complete[1](); await settle(); assert.equal(applied, 1);
  stop(); assert.ok(signals[1].aborted);
});
test('慢請求尚未完成時不重疊輪詢，完成後可繼續', async t => {
  const f = fixture(t); let complete; let calls = 0;
  const stop = pollWhileVisible(async () => { calls++; await new Promise(resolve => { complete=resolve; }); }, 3000);
  const tick = [...f.timers.values()][0]; void tick(); void tick(); assert.equal(calls, 1);
  complete(); await settle(); void tick(); assert.equal(calls, 2);
  complete(); await settle(); stop();
});
