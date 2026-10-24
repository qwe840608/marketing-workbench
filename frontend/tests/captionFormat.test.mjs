import test from 'node:test';
import assert from 'node:assert/strict';
import { applyFormat } from '../src/captionFormat.ts';
import { toPlatformText } from '../src/markdownText.ts';

const run = (text, kind, start = 0, end = text.length) => applyFormat(text, start, end, kind);

test('編號：選取的非空行依序加上 1. 2. 3.，空行保留；再按一次移除', () => {
  const text = '第一點\n第二點\n\n第三點';
  const numbered = run(text, 'numbered');
  assert.equal(numbered.text, '1. 第一點\n2. 第二點\n\n3. 第三點');
  assert.deepEqual([numbered.start, numbered.end], [0, numbered.text.length]);
  assert.equal(run(numbered.text, 'numbered').text, text);
});

test('清單只作用在選取到的行，沒選取時是游標所在行', () => {
  const text = '開頭\n甲\n乙\n結尾';
  assert.equal(run(text, 'bullet', 4, 6).text, '開頭\n- 甲\n- 乙\n結尾');
  assert.equal(run(text, 'numbered', 3, 3).text, '開頭\n1. 甲\n乙\n結尾');
  // 選取結尾停在下一行開頭時不算下一行。
  assert.equal(run(text, 'bullet', 3, 5).text, '開頭\n- 甲\n乙\n結尾');
  // 項目符號換成編號會取代原符號。
  assert.equal(run('- 甲\n- 乙', 'numbered').text, '1. 甲\n2. 乙');
});

test('大小標題：每行前面加 # 或 ## ，已有時移除；兩種標題與清單互換', () => {
  assert.equal(run('＜重點＞ 今天', 'h1').text, '# ＜重點＞ 今天');
  assert.equal(run('# 重點', 'h1').text, '重點');
  assert.equal(run('## 重點', 'h2').text, '重點');
  assert.equal(run('## 重點', 'h1').text, '# 重點');
  assert.equal(run('# 重點', 'h2').text, '## 重點');
  assert.equal(run('內文\n小標\n內文', 'h1', 4, 4).text, '內文\n# 小標\n內文');
  assert.equal(run('1. 小標', 'h1').text, '# 小標');
  assert.equal(run('   ', 'h1').text, '   ');
});

test('粗體：選取的文字包上 **，空白留在外面；再按一次移除', () => {
  const text = '新品 Sale 中文';
  const once = run(text, 'bold', 2, 8);
  assert.equal(once.text, '新品 **Sale** 中文');
  assert.equal(once.text.slice(once.start, once.end), 'Sale');
  const twice = run(once.text, 'bold', once.start, once.end);
  assert.equal(twice.text, text);
  assert.equal(run('**重點**', 'bold').text, '重點');
  // 沒選取：整行（不含清單符號）包上 **。
  assert.equal(run('- 重點\n下一行', 'bold', 3, 3).text, '- **重點**\n下一行');
  assert.equal(run('甲\n\n乙', 'bold').text, '**甲**\n\n**乙**');
});

test('按鈕產生的 Markdown 發佈時轉成平台顯示得出的格式', () => {
  const text = run(run('Hi 新品', 'bold').text, 'h1').text;
  assert.equal(text, '# **Hi 新品**');
  assert.equal(toPlatformText(run('Hi 新品', 'h1').text), '█ 𝗛𝗶 新品');
  assert.equal(toPlatformText(run('Hi 新品', 'h2').text), '▍𝗛𝗶 新品');
  assert.equal(toPlatformText(run('Hi 新品', 'bold').text), '𝗛𝗶 新品');
  assert.equal(toPlatformText(run('甲\n乙', 'bullet').text), '• 甲\n• 乙');
});
