"""文案框裡的 Markdown 在發佈時轉成平台顯示得出來的純文字。

社群平台都不支援 Markdown：# 大標題 → █ 大標題、## 小標題 → ▍小標題（英數粗體）、
**粗體**／*斜體* → Unicode 數學無襯線字形
（只有英文字母與數字有字形，中文只去掉符號）、行首 - ／* ／+ 項目 → •、[文字](網址) → 文字 網址、
`程式碼` → 程式碼；1. 編號維持原樣。規則與前端 markdownText.toPlatformText 相同，
共用 shared/caption_markdown_vectors.json。
"""

import re

STYLES = {
    "bold": (0x1D5D4, 0x1D5EE, 0x1D7EC),
    "italic": (0x1D608, 0x1D622, None),
}
HEADING = re.compile(r"^([ \t]*)(#{1,6})[ \t]+(.+?)[ \t]*$", re.M)
BULLET = re.compile(r"^([ \t]*)[-*+][ \t]+(?=\S)", re.M)
BOLD = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")
# JS 的 (?<![\p{L}\p{N}*]) 與 (?<![\p{L}\p{N}_])：[^\W_] 是字母與數字。
ITALIC = re.compile(r"(?<![^\W_])(?<!\*)\*([^*\s][^*\n]*)\*(?!\*)|(?<!\w)_([^_\s][^_\n]*)_(?!_)")
LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`\n]+)`")


def styled(text, style):
    upper, lower, digit = STYLES[style]

    def convert(ch):
        code = ord(ch)
        if 65 <= code <= 90:
            return chr(upper + code - 65)
        if 97 <= code <= 122:
            return chr(lower + code - 97)
        if 48 <= code <= 57 and digit:
            return chr(digit + code - 48)
        return ch

    return "".join(convert(ch) for ch in text)


def inline(text):
    text = BOLD.sub(lambda m: styled(m.group(1) or m.group(2) or "", "bold"), text)
    text = ITALIC.sub(lambda m: styled(m.group(1) or m.group(2) or "", "italic"), text)
    text = LINK.sub(r"\1 \2", text)
    return CODE.sub(r"\1", text)


def to_platform_text(text):
    text = HEADING.sub(
        lambda m: m.group(1)
        + ("█ " if len(m.group(2)) == 1 else "▍")
        + styled(inline(m.group(3)), "bold"),
        text,
    )
    text = BULLET.sub(r"\1• ", text)
    return "\n".join(inline(line) for line in text.split("\n"))
