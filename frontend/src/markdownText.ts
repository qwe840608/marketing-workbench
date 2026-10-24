// 社群平台都不支援 Markdown：文案框可以寫 Markdown，發佈時用 toPlatformText 轉成平台顯示得出來的純文字。
// 規則與後端 caption_markdown.to_platform_text 相同，共用 shared/caption_markdown_vectors.json。

const MARKDOWN = /\*\*[^*\n]+\*\*|__[^_\n]+__|(?<![\p{L}\p{N}*])\*[^*\s][^*\n]*\*(?!\*)|(?<![\p{L}\p{N}_])_[^_\s][^_\n]*_(?!_)|^#{1,6} \S|\[[^\]\n]+\]\([^)\s]+\)|`[^`\n]+`/mu;

export function hasMarkdown(text: string) {
  return MARKDOWN.test(text);
}

// 數學無襯線粗體／斜體：社群平台最常用、多數裝置都能顯示的字形。
const STYLES = {
  bold: { upper: 0x1d5d4, lower: 0x1d5ee, digit: 0x1d7ec },
  italic: { upper: 0x1d608, lower: 0x1d622, digit: null },
} as const;

function styled(text: string, style: keyof typeof STYLES) {
  const map = STYLES[style];
  return Array.from(text, ch => {
    const code = ch.codePointAt(0)!;
    if (code >= 65 && code <= 90) return String.fromCodePoint(map.upper + code - 65);
    if (code >= 97 && code <= 122) return String.fromCodePoint(map.lower + code - 97);
    if (code >= 48 && code <= 57 && map.digit) return String.fromCodePoint(map.digit + code - 48);
    return ch;
  }).join('');
}

// 發佈時送出的文字：# 大標題 → █ 大標題、## 小標題 → ▍小標題（英數粗體）、**粗體**／*斜體* → Unicode 字形（中文只去掉符號）、
// 行首 - ／* ／+ 項目 → •、[文字](網址) → 文字 網址、`程式碼` → 程式碼；1. 編號維持原樣。
export function toPlatformText(text: string) {
  return text
    .replace(/^([ \t]*)(#{1,6})[ \t]+(.+?)[ \t]*$/gmu, (_, lead: string, level: string, title: string) => lead + (level.length === 1 ? '█ ' : '▍') + styled(inline(title), 'bold'))
    .replace(/^([ \t]*)[-*+][ \t]+(?=\S)/gmu, '$1• ')
    .split('\n').map(inline).join('\n');
}

function inline(text: string) {
  return text
    .replace(/\*\*([^*\n]+)\*\*|__([^_\n]+)__/gu, (_, a?: string, b?: string) => styled(a ?? b ?? '', 'bold'))
    .replace(/(?<![\p{L}\p{N}*])\*([^*\s][^*\n]*)\*(?!\*)|(?<![\p{L}\p{N}_])_([^_\s][^_\n]*)_(?!_)/gu, (_, a?: string, b?: string) => styled(a ?? b ?? '', 'italic'))
    .replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/gu, '$1 $2')
    .replace(/`([^`\n]+)`/gu, '$1');
}
