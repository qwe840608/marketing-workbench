import test from 'node:test';
import assert from 'node:assert/strict';
import { ideationChoiceKey, selectIdeationChoice } from '../src/aiChoice.ts';
import { agentProvider, executionLabel, isRetiredProvider } from '../src/providers.ts';

const options = ['gemini_api', 'openai_api', 'anthropic_api'].map(provider => ({ provider, model: provider + '-model', available: true }));
const only = name => options.map(o => ({ ...o, available: o.provider === name }));

test('主題發想執行方式：瀏覽器記憶、品牌預設 AI、第一個可用 API', () => {
  assert.equal(selectIdeationChoice(options, 'openai_api', 'anthropic_api'), 'openai_api');
  for (const saved of [null, {}, 42, 'missing_api']) {
    assert.equal(selectIdeationChoice(options, saved, 'anthropic_api'), 'anthropic_api');
  }
  for (const fallback of ['', 'missing_api']) assert.equal(selectIdeationChoice(options, null, fallback), 'gemini_api');
  assert.equal(selectIdeationChoice(only('openai_api'), 'gemini_api', 'anthropic_api'), 'openai_api');
});

test('舊的本機 CLI 記憶或預設值一律略過', () => {
  for (const retired of ['codex_cli', 'claude_cli', 'agy_cli']) {
    assert.equal(selectIdeationChoice(options, retired, 'anthropic_api'), 'anthropic_api');
    assert.equal(selectIdeationChoice(options, null, retired), 'gemini_api');
    assert.equal(selectIdeationChoice([], retired, retired), agentProvider);
  }
});

test('沒有可用 API 時預設為交給 Agent 撰寫；記憶選過 Agent 則維持', () => {
  const none = options.map(o => ({ ...o, available: false }));
  assert.equal(selectIdeationChoice(none, null, 'gemini_api'), agentProvider);
  assert.equal(selectIdeationChoice([], 'openai_api', ''), agentProvider);
  assert.equal(selectIdeationChoice(options, agentProvider, 'gemini_api'), agentProvider);
  assert.equal(selectIdeationChoice(none, agentProvider, ''), agentProvider);
});

test('記憶以品牌區分', () => {
  assert.equal(ideationChoiceKey('12'), 'ideation-choice:12');
  assert.notEqual(ideationChoiceKey('12'), ideationChoiceKey('13'));
});

test('執行方式名稱：API、Agent，以及舊紀錄裡已停用的 CLI', () => {
  assert.equal(executionLabel('gemini_api'), 'Gemini API');
  assert.equal(executionLabel(agentProvider), '交給 Agent 撰寫');
  assert.equal(executionLabel('codex_cli'), 'Codex CLI（已停用）');
  assert.equal(executionLabel('claude_cli'), 'Claude Code（已停用）');
  assert.equal(executionLabel('agy_cli'), 'Antigravity（已停用）');
  assert.equal(executionLabel('unknown'), '已停用的執行方式');
  assert.equal(isRetiredProvider('codex_cli'), true);
  assert.equal(isRetiredProvider('openai_api'), false);
});
