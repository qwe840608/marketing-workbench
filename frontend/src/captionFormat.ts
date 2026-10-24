// 文案格式按鈕：插入 Markdown 語法（# 大標題、## 小標題、**粗體**、1. 編號、- 項目），再按一次移除。
// 平台不顯示 Markdown；發佈時由 markdownText.toPlatformText（後端 caption_markdown）轉成平台顯示得出來的格式。
// start／end 是 textarea 的 selectionStart／selectionEnd（UTF-16 位置）。

export type CaptionFormat = 'h1' | 'h2' | 'bold' | 'numbered' | 'bullet';
export type FormatResult = { text: string; start: number; end: number };

const LIST_PREFIX = /^(?:\d+\. |[-*•] )/;
const HEADING = /^#{1,6} /;

// 選取範圍擴大到完整行；沒有選取時就是游標所在行。
function lineRange(text: string, start: number, end: number) {
  const from = text.lastIndexOf('\n', start - 1) + 1;
  const stop = end > start && text[end - 1] === '\n' ? end - 1 : end;
  const next = text.indexOf('\n', stop);
  return { from, to: next < 0 ? text.length : next };
}

// 每個非空行加上行首符號；每行都已經有同一種就移除。
function prefixLines(lines: string[], kind: Exclude<CaptionFormat, 'bold'>) {
  const filled = lines.filter(line => line.trim());
  const marker = kind === 'h1' ? /^# / : kind === 'h2' ? /^#{2,6} / : kind === 'numbered' ? /^\d+\. / : /^- /;
  const strip = kind === 'h1' || kind === 'h2' ? HEADING : LIST_PREFIX;
  if (filled.length && filled.every(line => marker.test(line))) return lines.map(line => line.replace(strip, ''));
  let n = 0;
  const prefix = () => kind === 'h1' ? '# ' : kind === 'h2' ? '## ' : kind === 'numbered' ? `${++n}. ` : '- ';
  // 大小標題與清單互換時取代原本的符號。
  return lines.map(line => line.trim() ? prefix() + line.replace(HEADING, '').replace(LIST_PREFIX, '') : line);
}

// 粗體：每個非空行的文字（不含行首清單／標題符號與前後空白）包上 **；全部已包住就移除。
function boldLines(lines: string[]) {
  const parts = lines.map(line => /^(\s*(?:#{1,6} |\d+\. |[-*•] )?\s*)(.*?)(\s*)$/u.exec(line)!.slice(1));
  const filled = parts.filter(([, body]) => body);
  const bolded = (body: string) => body.length > 4 && body.startsWith('**') && body.endsWith('**');
  const remove = filled.length > 0 && filled.every(([, body]) => bolded(body));
  return parts.map(([lead, body, tail]) => body ? lead + (remove ? body.slice(2, -2) : '**' + body + '**') + tail : lead + body + tail);
}

export function applyFormat(text: string, start: number, end: number, kind: CaptionFormat): FormatResult {
  if (kind === 'bold' && start !== end) {
    // 選取的文字外面剛好是 ** 時移除，否則包住選取的文字。
    if (text.slice(start - 2, start) === '**' && text.slice(end, end + 2) === '**') {
      return { text: text.slice(0, start - 2) + text.slice(start, end) + text.slice(end + 2), start: start - 2, end: end - 2 };
    }
    const selected = text.slice(start, end);
    if (selected.includes('\n')) {
      const replaced = boldLines(selected.split('\n')).join('\n');
      return { text: text.slice(0, start) + replaced + text.slice(end), start, end: start + replaced.length };
    }
    const body = selected.trim();
    if (!body) return { text, start, end };
    if (body.length > 4 && body.startsWith('**') && body.endsWith('**')) {
      const replaced = selected.replace(body, body.slice(2, -2));
      return { text: text.slice(0, start) + replaced + text.slice(end), start, end: start + replaced.length };
    }
    // 粗體符號緊貼文字，前後空白留在外面。
    const lead = selected.length - selected.trimStart().length, tail = selected.length - selected.trimEnd().length;
    return { text: text.slice(0, start + lead) + '**' + body + '**' + text.slice(end - tail), start: start + lead + 2, end: start + lead + 2 + body.length };
  }
  const { from, to } = lineRange(text, start, end);
  const lines = text.slice(from, to).split('\n');
  const replaced = (kind === 'bold' ? boldLines(lines) : prefixLines(lines, kind)).join('\n');
  return { text: text.slice(0, from) + replaced + text.slice(to), start: from, end: from + replaced.length };
}
