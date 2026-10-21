"""Composer text counting shares fixed vectors and Unicode data with the frontend."""
import json
import unicodedata
from pathlib import Path

import pytest

from app.services.publish_rules import EMOJI, text_length

VECTOR_PATH = Path(__file__).resolve().parents[2] / "shared/publish_threads_vectors.json"
VECTORS = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["name"])
def test_shared_threads_vectors(case):
    assert text_length(case["text"]) == case["length"]


def test_shared_unicode_tables_match_backend():
    assert VECTORS["emoji_pattern"] == EMOJI.pattern
    actual = {i for i in range(0x110000) if unicodedata.combining(chr(i))}
    shared = {i for a, b in VECTORS["combining_ranges"] for i in range(a, b + 1)}
    assert actual == shared
