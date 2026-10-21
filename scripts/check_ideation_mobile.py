"""主題發想在四個平台分頁（FB／IG／Threads／YouTube）時，手機與桌面都不得撐寬頁面。

2026-10-14 使用者回報：手機上平台分頁一排放不下，最後一個分頁把 .ideation-page 撐到
469px（螢幕 390px），iPhone Safari 整頁可左右滑、左側文字被切掉。隔離資料原本只有
FB／IG 兩個分頁所以沒抓到；這裡補 Threads、YouTube 帳號與貼文重現該情境。
"""

import sys
from datetime import timedelta

from browser_harness import main, serve
from playwright.sync_api import expect
from ui_navigation import navigate


def seed():
    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Account, Brand, Post
    from app.models.base import utc_now
    from sqlalchemy import select

    engine = build_engine(Settings())
    try:
        with session_factory(engine).begin() as s:
            if s.scalar(select(Account).where(Account.platform == "threads")):
                return
            brand = s.scalar(select(Brand).where(Brand.slug == "TEST"))
            for platform in ("instagram", "threads", "youtube"):
                account = Account(
                    brand_id=brand.id,
                    platform=platform,
                    external_id=f"mobile-{platform}",
                    name=f"[隔離驗收] {platform}",
                    send_enabled=False,
                    token_ref="META_PAGE_ACCESS_TOKEN",
                )
                s.add(account)
                s.flush()
                for n in range(3):
                    s.add(Post(
                        account_id=account.id,
                        external_id=f"mobile-{platform}-{n}",
                        caption="[隔離驗收] 很長的貼文標題用來測試手機版面不被撐寬 " * 3,
                        media_type="POST",
                        published_at=utc_now() - timedelta(hours=n + 1),
                    ))
    finally:
        engine.dispose()


# 超出視窗的元素必須被某個「可捲動或裁切」且本身在視窗內的祖先容器包住；
# 頁面與主要捲動容器本身也不得比可視寬度寬。
MEASURE = """() => {
  const page = document.querySelector('.ideation-page');
  const loose = [...page.querySelectorAll('*')].filter(e => {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.right <= innerWidth + 1) return false;
    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
      const o = getComputedStyle(a).overflowX;
      if (o !== 'visible' && a.getBoundingClientRect().right <= innerWidth + 1) return false;
      if (a === page) break;
    }
    return true;
  }).map(e => e.tagName + '.' + (e.className || '').toString().slice(0, 40));
  return {
    loose,
    page: [page.scrollWidth, page.clientWidth],
    root: [document.documentElement.scrollWidth, innerWidth],
    tabs: [...document.querySelectorAll('.ideation-platform-tabs button')].map(b => b.textContent),
  };
}"""


def exercise(page, _unused, shot, checks):
    seed()
    page.reload()
    navigate(page, "主題發想")
    tabs = page.locator(".ideation-platform-tabs button")
    expect(tabs).to_have_count(4)
    page.wait_for_load_state("networkidle")
    result = page.evaluate(MEASURE)
    width = page.viewport_size["width"]
    assert result["loose"] == [], (width, result)
    assert result["page"][0] <= result["page"][1] + 1, (width, result)
    assert result["root"][0] <= result["root"][1] + 1, (width, result)
    # 最後一個分頁仍可捲到並點選。
    tabs.last.scroll_into_view_if_needed()
    tabs.last.click()
    expect(tabs.last).to_have_attribute("aria-selected", "true")
    assert page.evaluate(MEASURE)["page"][0] <= result["page"][1] + 1
    shot("ideation-four-tabs")
    checks.append(f"ideation-four-tabs-no-overflow-{width}")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        main(exercise=exercise)
