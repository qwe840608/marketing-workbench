"""Synthetic Agent MCP content and HTTP/jev doubles; never used in production."""

from datetime import timedelta

import httpx


def seed_content(factory, brand_id):
    from app.models import Account, Classification, Contact, Message, MetricSnapshot, Post, Thread
    from app.models.base import utc_now
    from app.services.branding import put_setting

    now = utc_now()
    with factory.begin() as session:
        put_setting(session, f"ideation.brand.{brand_id}", {"topics": ["服務流程", "其他"]})
        put_setting(session, f"brand.rules.{brand_id}", {"forbidden_phrases": ["保證改善"]})
        account = Account(brand_id=brand_id, platform="instagram", external_id="88770011",
                          name="隔離驗收帳號", token_ref="META_PAGE_ACCESS_TOKEN")
        session.add(account)
        session.flush()
        post = Post(account_id=account.id, external_id="agent-post", caption="流程說明",
                    media_type="IMAGE", published_at=now - timedelta(days=2))
        contact = Contact(brand_id=brand_id, platform="instagram", external_id="fake-platform-id",
                          display_name="測試觀眾名字")
        session.add_all([post, contact])
        session.flush()
        thread = Thread(account_id=account.id, brand_id=brand_id, post_id=post.id,
                        contact_id=contact.id, external_id="agent-comments", kind="comment_thread")
        session.add(thread)
        session.flush()
        ids = []
        for index in range(3):
            message = Message(thread_id=thread.id, contact_id=contact.id,
                              external_id=f"agent-comment-{index}", direction="in", author_type="fan",
                              text=f"服務流程第 {index} 步？測試觀眾名字 fake-platform-id "
                              "＠fake.viewer 電話 0912345678 Email audience@example.test",
                              sent_at=now - timedelta(hours=1), comment_parent_known=True)
            session.add(message)
            session.flush()
            session.add(Classification(message_id=message.id, engine="jev", intent="other",
                                       sentiment="neutral", sensitive=False, action="classified",
                                       confidence=1))
            ids.append(message.id)
        session.add(MetricSnapshot(post_id=post.id, captured_at=now, reach=40, likes=3, comments=3))
        return {"post_id": post.id, "message_ids": ids, "account_id": account.id,
                "thread_id": thread.id}


def typed(state, questions, settings):
    from app.services import jev

    answers = {}
    for key, question in questions.items():
        kind = question["type"]
        if kind == "choice":
            choice = next(iter(question["criteria"]))
            answers[key] = {"type": kind, "choice": choice, "confidence": 1,
                            "probabilities": {c: float(c == choice) for c in question["criteria"]}}
        elif kind == "score":
            answers[key] = {"type": kind, "score": 2, "confidence": 1,
                           "legend": {str(i): c for i, c in enumerate(question["criteria"])},
                           "probabilities": {str(i): float(i == 2)
                                             for i in range(len(question["criteria"]))}}
        else:
            answers[key] = {"type": kind, "noul": 1 if key == "question" else 0}
    return jev.Result({"model": "isolated-jev", "answers": answers,
                       "usage": {"input_tokens": 10, "output_tokens": 3}}, 0)


def no_ai(*args, **kwargs):
    raise AssertionError("Agent content must never invoke text generation")


def fetch_comments(factory, settings, post_id):
    from app.models.base import utc_now
    from app.services.gateway_workers import Workers
    from app.services import credentials
    from pydantic import SecretStr

    settings.meta_ig_account_id = "88770011"
    settings.meta_page_access_token = SecretStr("isolated-meta-secret")

    calls = []

    def handler(request):
        assert request.method == "GET" and request.url.path.endswith("/comments")
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "mock-fetched-agent-comment",
            "text": "服務流程開始前需要準備什麼？", "timestamp":
            (utc_now() - timedelta(minutes=20)).isoformat(),
            "from": {"id": "mock-fan", "username": "mock_viewer"}}]})

    existing_engine = credentials._ENGINES.get(settings.database_path)
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            def request(method, url, *, headers=None, qs=None, body=None, timeout=15):
                response = http.request(method, url, headers=headers, params=qs, json=body)
                return {"statusCode": response.status_code, "body": response.json(), "headers": {}}

            result = Workers(factory, settings, request=request).comments(
                requested_only=True, post_id=post_id)
    finally:
        # A worker-owned credential pool must release the synthetic DB before scratch cleanup.
        if existing_engine is None:
            cached = credentials._ENGINES.pop(settings.database_path, None)
            if cached is not None:
                cached.dispose()
    assert calls, result
    return result


def ideas_for(evidence):
    group = next(group for group in evidence["groups"] if group["quotes"])
    return [{"topic": group["topic"], "title": f"流程確認主題 {index + 1}", "goal": goal,
             "hook": "開始前先確認需求", "angle": "說明準備流程與觀點",
             "keyword": "流程確認", "element": "反差", "visual": "POV 與側拍示意準備流程",
             "quote_ids": [group["quotes"][0]["id"]]}
            for goal in ("變現型", "流量型", "引流型") for index in range(5)]


def script_content():
    return {"title": "流程準備腳本", "goal": "流量型", "hook": "開始前先確認需求",
            "duration_seconds": 10, "shots": [{"number": 1, "visual": "現場準備",
                "camera": "POV／側拍", "dialogue": "先確認需求，再討論流程。",
                "subtitle": "確認需求", "sound": "ASMR 整理聲", "seconds": 10,
                "b_roll": "用品近拍"}], "ending": "", "notes": "品牌資料待品牌覆核",
            "permissions": "場地與肖像授權待確認"}
