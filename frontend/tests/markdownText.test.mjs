import test from 'node:test';
import assert from 'node:assert/strict';
import { hasMarkdown, toUnicodeStyles } from '../src/markdownText.ts';

test('偵測常見 Markdown 語法，hashtag 與一般文字不算', () => {
  for (const text of ['這是 **重點**', '__bold__', '這是 *斜體* 喔', '# 標題', '[連結](https://example.com)', '`code`']) {
    assert.equal(hasMarkdown(text), true, text);
  }
  for (const text of ['#主題 #標籤', '一般文案 @帳號', '2*3=6', 'snake_case_name', '價格 5 * 2']) {
    assert.equal(hasMarkdown(text), false, text);
  }
});

test('粗體、斜體轉成 Unicode 字形，中文維持原樣並移除符號', () => {
  assert.equal(toUnicodeStyles('**Hi 2026**'), '𝗛𝗶 𝟮𝟬𝟮𝟲');
  assert.equal(toUnicodeStyles('*new*'), '𝘯𝘦𝘸');
  assert.equal(toUnicodeStyles('**中文 OK**'), '中文 𝗢𝗞');
  assert.equal(toUnicodeStyles('# Title'), '𝗧𝗶𝘁𝗹𝗲');
  assert.equal(toUnicodeStyles('[看這裡](https://example.com)'), '看這裡 https://example.com');
  assert.equal(toUnicodeStyles('#主題 不變'), '#主題 不變');
});
