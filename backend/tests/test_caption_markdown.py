"""文案 Markdown 轉換與前端共用固定向量。"""

import json
from pathlib import Path

import pytest

from app.services.caption_markdown import to_platform_text

VECTOR_PATH = Path(__file__).resolve().parents[2] / "shared/caption_markdown_vectors.json"
CASES = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_caption_markdown_vectors(case):
    assert to_platform_text(case["text"]) == case["expected"]
