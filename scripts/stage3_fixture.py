"""Explicitly synthetic content for isolated stage 3 UI checks only."""

from datetime import timedelta

from sqlalchemy import select

from app.models import Brand
from app.models.base import utc_now
from app.models.ideation import IdeationReport, ScriptVersion, VideoScript
from app.services.ideation import REVIEW_NOTICE


def seed_stage3(factory, origin):
    with factory.begin() as s:
        brand = s.scalar(select(Brand).where(Brand.slug == "TEST"))
        q = {
            "id": 1,
            "text": "[隔離驗收] 客製方案服務前，需要先確認哪些現場條件？",
            "platform": "facebook",
            "url": origin + "/?view=ideation&message_id=1",
            "pain": 2,
            "is_question": True,
        }
        group = {
            "topic": "需求類型與處理",
            "count": 12,
            "previous_count": 8,
            "change": 4,
            "pain": 2.5,
            "dm_conversations": 8,
            "booked_conversations": 3,
            "booking_weight": 1.375,
            "fallback_count": 1,
            "selection_method": "jev",
            "quotes": [q],
        }
        idea = {
            "topic": "需求類型與處理",
            "title": "[隔離驗收] 客製方案服務，先看維修口與現場空間",
            "goal": "引流型",
            "hook": "想洗客製方案服務，先拍這兩個地方。",
            "angle": "從觀眾的現場條件疑問出發，說明評估流程。",
            "keyword": "客製方案服務評估",
            "element": "反差",
            "visual": "POV 與側拍對照維修空間",
            "quote_ids": [1],
        }
        report = IdeationReport(
            brand_id=brand.id,
            meeting_at=utc_now() + timedelta(days=1),
            start_at=utc_now() - timedelta(days=30),
            end_at=utc_now(),
            trigger="manual",
            provider="gemini_api",
            status="ready",
            notification_status="suppressed",
            data_json={
                "notice": REVIEW_NOTICE,
                "ideas": [idea],
                "groups": [group],
                "booking_note": "隔離驗收資料，非真實營運數據。權重按不重複對話計算，關聯不代表因果。",
                "quote_note": "原話不足三則時不補造。",
                "comparison_partial": False,
                "empty": False,
            },
        )
        s.add(report)
        s.flush()
        content = {
            "title": idea["title"],
            "goal": "引流型",
            "hook": idea["hook"],
            "duration_seconds": 20,
            "shots": [
                {
                    "number": 1,
                    "visual": "維修口與空間示意",
                    "camera": "POV",
                    "dialogue": "先確認維修口與工作空間，再由品牌評估服務方式。",
                    "subtitle": "先確認現場條件",
                    "sound": "現場環境聲與 ASMR 環境聲",
                    "seconds": 10,
                    "b_roll": "設備外觀近拍",
                },
                {
                    "number": 2,
                    "visual": "工作前防護示意",
                    "camera": "側拍",
                    "dialogue": "實際處理方式交由專人確認。",
                    "subtitle": "依現場評估",
                    "sound": "防護布鋪設聲",
                    "seconds": 10,
                    "b_roll": "收納與防護細節",
                },
            ],
            "ending": "",
            "notes": REVIEW_NOTICE,
            "permissions": "場地、肖像、商標與音樂授權待確認；不使用其他品牌素材。",
        }
        review = {
            "passed": False,
            "reasons": ["隔離驗收：觀眾問題仍需補充說明"],
            "notice": REVIEW_NOTICE,
        }
        script = VideoScript(
            brand_id=brand.id,
            report_id=report.id,
            topic_index=0,
            title=content["title"],
            content_json=content,
            review_json=review,
            provider="gemini_api",
            model="isolated-fixture",
        )
        s.add(script)
        s.flush()
        s.add(
            ScriptVersion(
                script_id=script.id,
                revision=1,
                content_json=content,
                review_json=review,
                actor="test:fixture",
            )
        )
        return report.id, script.id
