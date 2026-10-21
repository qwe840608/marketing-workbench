// 社群平台都不支援 Markdown：偵測常見語法以提示使用者，並可把粗體／斜體轉成 Unicode 字形（只限英文字母與數字）。

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

export function toUnicodeStyles(text: string) {
  return text
    .replace(/^#{1,6} (.+)$/gmu, (_, title: string) => styled(title, 'bold'))
    .replace(/\*\*([^*\n]+)\*\*|__([^_\n]+)__/gu, (_, a?: string, b?: string) => styled(a ?? b ?? '', 'bold'))
    .replace(/(?<![\p{L}\p{N}*])\*([^*\s][^*\n]*)\*(?!\*)|(?<![\p{L}\p{N}_])_([^_\s][^_\n]*)_(?!_)/gu, (_, a?: string, b?: string) => styled(a ?? b ?? '', 'italic'))
    .replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/gu, '$1 $2')
    .replace(/`([^`\n]+)`/gu, '$1');
}
