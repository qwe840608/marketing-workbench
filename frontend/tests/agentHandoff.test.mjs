import test from 'node:test';
import assert from 'node:assert/strict';
import { handoffLinks } from '../src/agentHandoff.ts';

test('三個桌面 App 連結用官方格式並完整編碼指令', () => {
  const plain = '請用 get_guide("ideas") 接手主題報告 #7&x=1';
  const links = handoffLinks({ slash: '/mwb:ideas 接手主題報告 #7', plain });
  assert.deepEqual(links.map(l => l.app), ['claude-code', 'claude-chat', 'codex']);
  const [code, chat, codex] = links.map(l => new URL(l.href));
  assert.equal(code.protocol + code.host + code.pathname, 'claude:code/new');
  assert.equal(code.searchParams.get('q'), '/mwb:ideas 接手主題報告 #7');
  assert.equal(chat.protocol + chat.host + chat.pathname, 'claude:claude.ai/new');
  assert.equal(chat.searchParams.get('q'), plain);
  assert.equal(codex.protocol + codex.host + codex.pathname, 'codex:new');
  assert.equal(codex.searchParams.get('prompt'), plain);
  assert.equal(codex.searchParams.get('mode'), 'codex');
  assert.equal([...codex.searchParams.keys()].length, 2);
});
