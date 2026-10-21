"""Local promise gate remains mandatory with jev unavailable; sends use HTTP mock."""

import pytest

from app.services.content_safety import forbidden_promise


@pytest.mark.parametrize(
    "text,blocked",
    [
        ("提升成效效果因需求類型而異，不做保證", False),
        ("服務後提升成效效果，不保證", False),
        ("服務後是否提升成效，無法保證", False),
        ("改善困擾的效果，不能保證", False),
        ("服務後提升成效效果因需求類型而異", False),
        ("服務後不一定會提升成效", False),
        ("未必能改善困擾", False),
        ("不能保證100%達成效果", False),
        ("無法保證達成目標", False),
        ("我們不保證提升成效", False),
        ("不會解決問題，我們不保證提升成效", False),
        ("提升成效效果，無法保證，請先提供需求類型", False),
        ("保證提升成效", True),
        ("一定提升成效，不騙你", True),
        ("一定提升成效，不做保證", True),
        ("提升成效有保證，不做保證", True),
        ("保證提升成效，效果因需求類型而異", True),
        ("百分之百達成效果", True),
        ("完全達成效果，不做保證", True),
        ("保證達成目標", True),
        ("保證１００％達成效果", True),
        ("不會解決問題但保證達成目標", True),
        ("不會解決問題而且完全達成效果", True),
        ("不會解決問題提升成效有保證", True),
        ("不做保證。服務後一定提升成效", True),
        ("提升成效。不做保證", True),
        ("提升成效，不保證解決問題", True),
        ("提升成效效果因需求類型而異，而且可以解決問題", True),
        ("提升成效效果因需求類型而異，保證達成目標", True),
    ],
)
def test_promise_scope(text, blocked):
    from brand_fixtures import FORBIDDEN
    assert forbidden_promise(text, FORBIDDEN) is blocked
