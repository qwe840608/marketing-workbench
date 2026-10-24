import test from 'node:test';
import assert from 'node:assert/strict';
import { hasMarkdown, toPlatformText } from '../src/markdownText.ts';

test('偵測常見 Markdown 語法，hashtag 與一般文字不算', () => {
  for (const text of ['這是 **重點**', '__bold__', '這是 *斜體* 喔', '# 標題', '[連結](https://example.com)', '`code`']) {
    assert.equal(hasMarkdown(text), true, text);
  }
  for (const text of ['#主題 #標籤', '一般文案 @帳號', '2*3=6', 'snake_case_name', '價格 5 * 2']) {
    assert.equal(hasMarkdown(text), false, text);
  }
});

test('發佈時的 Markdown 轉換與後端共用向量', async () => {
  const { default: vectors } = await import('../../shared/caption_markdown_vectors.json', { with: { type: 'json' } });
  for (const c of vectors.cases) assert.equal(toPlatformText(c.text), c.expected, c.name);
});
