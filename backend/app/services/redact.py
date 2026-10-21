"""雲端呼叫共用的本機個資遮蔽；不保留可還原的對照表。"""

import re
import unicodedata
from dataclasses import dataclass

PATTERNS = (
    (
        "LINE_ID",
        re.compile(
            r"(?i)(?:(?:LINE|賴)\s*(?:ID|帳號|帳號名稱)\s*(?:是|為|[:：=])?\s*"
            r"|(?:加我|我的)\s*(?:LINE|賴)\s*(?:是|為|[:：=])\s*)"
            r"[@a-z0-9][a-z0-9._-]{1,30}(?![a-z0-9._-])"
            r"|https?://(?:line\.me/(?:ti/p/|R/ti/p/)|lin\.ee/)[^\s，。；！？\"<>]+"
        ),
    ),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.UNICODE)),
    ("ID", re.compile(r"(?<![A-Za-z0-9])[A-Za-z][12ABCDabcd]\d{8}(?!\d)")),
    (
        "ADDRESS",
        re.compile(
            r"(?:[\u4e00-\u9fff]{2,3}[縣市])?"
            r"[\u4e00-\u9fff]{0,8}(?:區|鄉|鎮)?"
            r"[\u4e00-\u9fff]{1,10}(?:路|街|大道)"
            r"[\u4e00-\u9fff0-9之\-段巷弄]{0,18}\d+(?:之\d+)?號"
            r"(?:[\d一二三四五六七八九十]+[樓Ff](?:之\d+)?)?"
        ),
    ),
    (
        "PHONE",
        re.compile(
            r"(?<!\d)(?:(?:\+?886[\s()（）.-]*)?0?9(?:[\s.-]*\d){8}"
            r"|(?:\+?886[\s()（）.-]*|0)[2-8][\s()（）.-]*\d{3,4}[\s.-]*\d{4})"
            r"(?:\s*(?:分機|ext\.?|#)\s*\d{1,6})?(?!\d)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class Redacted:
    text: str
    counts: dict[str, int]


def redact(text: str) -> Redacted:
    # Preserve the requested typography without weakening full-width PII matching.
    punctuation = "，。！？：；「」（）"
    protected = {char: chr(0xF0000 + index) for index, char in enumerate(punctuation)}
    value = unicodedata.normalize("NFKC", text.translate(str.maketrans(protected)))
    value = value.translate(str.maketrans({v: k for k, v in protected.items()}))
    counts = {}
    for name, pattern in PATTERNS:
        value, count = pattern.subn(f"[REDACTED_{name}]", value)
        if count:
            counts[name.lower()] = count
    return Redacted(value, counts)


def scrub(value):
    if isinstance(value, str):
        return redact(value).text
    if isinstance(value, dict):
        return {str(key): scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value
