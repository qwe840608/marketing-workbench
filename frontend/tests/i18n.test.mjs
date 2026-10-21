import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { t } from '../src/i18n.ts';

const src = fileURLToPath(new URL('../src/', import.meta.url));
const languages = ['en', 'zh-CN', 'ja'];
const groups = ['app', 'publish', 'posts', 'guides', 'ai', 'settings', 'dashboard', 'backend'];
const walk = dir => readdirSync(dir).flatMap(name => {
  const full = path.join(dir, name);
  if (statSync(full).isDirectory()) return name === 'locales' ? [] : walk(full);
  return /\.tsx?$/.test(name) ? [full] : [];
});
const unescape = raw => raw.replace(/\\(.)/g, (_, c) => c === 'n' ? '\n' : c);
const keys = new Map();
const contextKeys = new Set();
for (const file of walk(src)) {
  for (const match of readFileSync(file, 'utf8').matchAll(/(?<![\w.$])t\(\s*'((?:[^'\\\n]|\\.)*)'/g)) keys.set(unescape(match[1]), path.relative(src, file));
  // tx(情境, 原文)：原文一定要有譯文；「情境|原文」是選填的情境譯文，不算過時字串。
  for (const match of readFileSync(file, 'utf8').matchAll(/(?<![\w.$])tx\(\s*'(\w+)',\s*'((?:[^'\\\n]|\\.)*)'/g)) {
    keys.set(unescape(match[2]), path.relative(src, file));
    contextKeys.add(`${match[1]}|${unescape(match[2])}`);
  }
}
const placeholders = text => [...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',');
const tables = Object.fromEntries(await Promise.all(languages.map(async lang => [lang, Object.fromEntries(await Promise.all(groups.map(async group => [group, (await import(`../src/locales/${lang}/${group}.ts`)).default])))])));

test('繁中直接回傳原文並代入變數', () => {
  assert.equal(t('登入工作檯'), '登入工作檯');
  assert.equal(t('已選 {count} 則', { count: 3 }), '已選 3 則');
});

test('程式中每個 t() 字串都有英文、簡中、日文翻譯，且變數名稱一致', () => {
  assert.ok(keys.size > 100, '應找到介面字串');
  const problems = [];
  for (const lang of languages) {
    const merged = Object.assign({}, ...Object.values(tables[lang]));
    for (const [key, file] of keys) {
      if (!(key in merged)) problems.push(`${lang} 缺少翻譯（${file}）：${key}`);
      else if (!merged[key].trim()) problems.push(`${lang} 翻譯為空：${key}`);
    }
    for (const [key, value] of Object.entries(merged)) {
      if (placeholders(key) !== placeholders(value)) problems.push(`${lang} 變數不一致：${key} → ${value}`);
    }
  }
  assert.deepEqual(problems, []);
});

test('翻譯表沒有程式已不再使用的字串（後端訊息除外）', () => {
  const stale = [];
  for (const lang of languages) for (const group of groups.filter(g => g !== 'backend')) {
    for (const key of Object.keys(tables[lang][group])) if (!keys.has(key) && !contextKeys.has(key)) stale.push(`${lang}/${group}：${key}`);
  }
  assert.deepEqual(stale, []);
});
