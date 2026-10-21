"Reuse existing export path guards, secret scrubbing, atomic writes and Word styles."
from functools import wraps
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import update

from app.db import DatabaseBusy
from app.logging_config import log_failure
from app.models import Brand
from app.models.ideation import IdeationReport, VideoScript
from app.services import export_docx, video_scripts
from app.services.date_ranges import report_comment_bounds
from app.services.export_data import ExportText, atomic_write, instant, root_path, segment
from app.services.export_md import literal
from app.services.ideation_links import quote_path

SHOT_KEYS = ["number", "visual", "camera", "dialogue", "subtitle", "sound", "seconds", "b_roll"]
SHOT_LABELS = ["鏡號", "畫面", "機位", "台詞／旁白", "字幕", "音效／ASMR", "時長（秒）", "B-roll"]


def safe_file(session, settings, value, format):
    from app.services.export_data import destination

    root = root_path(session, settings)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("匯出路徑不合法")
    relative = path.relative_to(root)
    path = destination(root, relative)
    if path.suffix != "." + format:
        raise ValueError("匯出格式不符")
    return path


def export_state(session, settings, row):
    record = row.export_json or {}
    state = {"files": [], "error": record.get("error")}
    if isinstance(row, VideoScript) and record.get("revision", row.version) != row.version:
        return {"files": [], "error": "此腳本版本尚未完成匯出"}
    try:
        brand = session.get(Brand, row.brand_id)
        folder = "scripts" if isinstance(row, VideoScript) else "ideation"
        stem = instant(row.created_at)[:10] + (
            "_" + segment(row.title) + f"--{row.id}-v{row.version}"
            if isinstance(row, VideoScript)
            else f"_例會素材--{row.id}"
        )
        # Older reports have no persisted result. Only recognize their unique copies.
        root = root_path(session, settings)
        for format in ("md", "docx"):
            value = record.get(format) or str(
                root / segment(brand.slug) / folder / (stem + "." + format)
            )
            path = safe_file(session, settings, value, format)
            exists = path.is_file()
            state["files"].append({"format": format, "path": str(path), "available": exists})
            if not exists and not state["error"]:
                state["error"] = "匯出檔案不存在或尚未完成；請確認匯出目錄與權限"
    except (ValueError, OSError):
        return {"files": [], "error": "匯出路徑不合法、超出目前匯出根目錄或無法存取"}
    return state


def download(access, settings, kind, identity, format):
    from app.services import ideation

    row = (
        ideation.get(access, identity) if kind == "reports" else video_scripts.get(access, identity)
    )
    state = export_state(access.session, settings, row)
    file = next((f for f in state["files"] if f["format"] == format and f["available"]), None)
    if not file:
        raise HTTPException(404, state["error"] or "找不到匯出檔案")
    return safe_file(access.session, settings, file["path"], format)


def record_export(model):
    def decorate(fn):
        @wraps(fn)
        def run(factory, settings, identity):
            with factory() as session:
                row = session.get(model, identity)
                revision = row.version if model is VideoScript else None
            try:
                paths = fn(factory, settings, identity)
                result = {"md": paths[0], "docx": paths[1], "error": None}
            except Exception as error:
                log_failure("mwb.ideation_exports", "ideation_exports_run_failed", error)
                # Exception messages may contain credentials or model text; use safe categories.
                reason = (
                    "沒有寫入權限"
                    if isinstance(error, PermissionError)
                    else "路徑不合法或超出匯出根目錄"
                    if isinstance(error, ValueError)
                    else "磁碟或檔案存取失敗"
                    if isinstance(error, OSError)
                    else "文件產生失敗"
                )
                result = {"error": "匯出失敗：" + reason}
                paths = []
            if revision is not None:
                result["revision"] = revision
            try:
                with factory.begin() as session:
                    statement = update(model).where(model.id == identity)
                    if revision is not None:
                        statement = statement.where(model.version == revision)
                    # Export metadata must not create an unreviewed script revision.
                    session.execute(statement.values(export_json=result))
            except DatabaseBusy as error:
                # 呼叫端都在內容提交後才匯出；記不到狀態也不能把已存好的內容回報成失敗。
                log_failure("mwb.ideation_exports", "ideation_exports_state_failed", error)
                result = {**result, "error": result["error"] or "匯出狀態未能記錄，請稍後重新整理"}
            # 內容已提交，匯出失敗只記在 export_json.error（export_state 顯示），不回 503。
            return result

        return run

    return decorate


def write_pair(session, settings, brand, folder, stem, markdown, doc):
    root = root_path(session, settings)
    relative = f"{segment(brand.slug)}/{folder}/{stem}"
    data = BytesIO()
    doc.save(data)
    paths = [
        atomic_write(root, relative + ".md", markdown.encode("utf-8")),
        atomic_write(root, relative + ".docx", data.getvalue()),
    ]
    return [str(p) for p in paths]


@record_export(IdeationReport)
def export_report(factory, settings, report_id):
    with factory() as session:
        row = session.get(IdeationReport, report_id)
        brand, clean = session.get(Brand, row.brand_id), ExportText(settings, session)
        doc = export_docx.document(clean(brand.name), "例會素材", session=session)
        notice = clean(row.data_json["notice"])
        period = f"貼文期間：{instant(row.start_at)} 至 {instant(row.end_at)}（不含結束時間，台北）"
        start, end = report_comment_bounds(row)
        comments = f"留言範圍：{instant(start)} 至 {instant(end)}（不含結束時間，台北）"
        lines = [
            f"# {literal(clean(brand.name))}｜例會素材",
            "",
            notice,
            "",
            period,
            comments,
            "",
            row.data_json["quote_note"],
            "",
        ]
        doc.add_paragraph(notice)
        doc.add_paragraph(period)
        doc.add_paragraph(comments)
        doc.add_paragraph(row.data_json["quote_note"])
        if row.data_json["comparison_partial"]:
            lines.append("前期有部分時間早於所選貼文發佈，變化僅供參考")
            doc.add_paragraph(lines[-1])
        if not row.data_json["ideas"]:
            lines.append("期間沒有可引用的觀眾文字；未產生主題，不補造資料。")
            doc.add_paragraph(lines[-1])
        for goal in ("變現型", "流量型", "引流型"):
            ideas = [idea for idea in row.data_json["ideas"] if idea["goal"] == goal]
            heading = f"{goal}（{len(ideas)} 題）"
            lines.extend(["## " + heading, ""])
            doc.add_heading(heading, 1)
            for idea in ideas:
                tags = " · ".join(clean(idea[key]) for key in ("goal", "element", "topic"))
                if not idea["quote_ids"]:
                    tags += " · 延伸主題"
                lines.extend([literal(tags), "", "### " + literal(clean(idea["title"])), ""])
                doc.add_paragraph(tags)
                doc.add_heading(clean(idea["title"]), 2)
                for label, key in [("開場", "hook"), ("切角", "angle"),
                                   ("可拍畫面", "visual"), ("關鍵字", "keyword")]:
                    text = label + "：" + clean(idea[key])
                    lines.extend([literal(text), ""])
                    doc.add_paragraph(text)
                text = "佐證原話 ID：" + "、".join(map(str, idea["quote_ids"]))
                lines.extend([text, ""])
                doc.add_paragraph(text)
                for group in row.data_json["groups"]:
                    if group["topic"] != idea["topic"]:
                        continue
                    for quote in group["quotes"]:
                        if quote["id"] in idea["quote_ids"]:
                            text = f"#{quote['id']}：{clean(quote['text'])}"
                            lines.extend(["> " + literal(text).replace("\n", "\n> "), ""])
                            doc.add_paragraph(text)
        stem = instant(row.created_at)[:10] + "_例會素材"
        # Canonical daily export plus immutable report copy prevents same-day report loss.
        write_pair(session, settings, brand, "ideation", stem, "\n".join(lines), doc)
        paths = write_pair(
            session, settings, brand, "ideation", stem + f"--{row.id}", "\n".join(lines), doc
        )
        return paths


@record_export(VideoScript)
def export_script(factory, settings, script_id):
    with factory() as session:
        row = session.get(VideoScript, script_id)
        state = video_scripts.view(session, row)
        brand, clean = session.get(Brand, row.brand_id), ExportText(settings, session)
        c = {k: clean(v) if isinstance(v, str) else v for k, v in row.content_json.items()}
        doc = export_docx.document(clean(brand.name), c["title"], session=session)
        lines = [
            "# " + literal(c["title"]),
            "",
            state["notice"],
            "",
            f"版本：{row.version}",
            "",
            "檢查：" + ("通過；仍需品牌覆核" if row.review_json["passed"] else "未通過／需修改"),
            "",
        ]
        for text in [
            state["notice"],
            f"版本：{row.version}",
            lines[-2],
            *row.review_json["reasons"],
        ]:
            doc.add_paragraph(clean(text))
        for label, key in [
            ("目標類型", "goal"),
            ("Hook", "hook"),
            ("片長（秒）", "duration_seconds"),
        ]:
            text = f"{label}：{c[key]}"
            lines.extend([literal(text), ""])
            doc.add_paragraph(text)
        for q in state["quotes"]:
            link = quote_path(q, row.brand_id, row.report_id)
            text = f"觀眾問題 #{q['id']} · {q['platform']}：{clean(q['text'])}"
            lines.extend([literal(text), "", link, ""])
            doc.add_paragraph(text)
            doc.add_paragraph(link)
        lines.extend(
            [
                "## 分鏡表",
                "",
                "| " + " | ".join(SHOT_LABELS) + " |",
                "| " + " | ".join(["---"] * 8) + " |",
            ]
        )
        for shot in c["shots"]:
            values = [clean(shot[k]) for k in SHOT_KEYS]
            lines.append(
                "| "
                + " | ".join(v.replace("|", "\\|").replace("\n", "<br>") for v in values)
                + " |"
            )
        doc.add_heading("分鏡表", 1)
        # A4 portrait: one compact two-column table per shot keeps all eight fields readable.
        for shot in c["shots"]:
            export_docx.table(
                doc,
                ["分鏡欄位", "內容"],
                [
                    (label, clean(shot[key]))
                    for label, key in zip(SHOT_LABELS, SHOT_KEYS, strict=True)
                ],
                [3, 14],
            )
            doc.add_paragraph("")
        for label, key in [
            ("品牌固定結尾", "ending"),
            ("拍攝備註", "notes"),
            ("需要的授權", "permissions"),
        ]:
            lines.extend(["", "## " + label, "", literal(c[key])])
            doc.add_heading(label, 1)
            doc.add_paragraph(c[key])
        lines.extend(["", "檢查問題：" + "；".join(clean(r) for r in row.review_json["reasons"])])
        stem = instant(row.created_at)[:10] + "_" + segment(c["title"])
        write_pair(session, settings, brand, "scripts", stem, "\n".join(lines), doc)
        paths = write_pair(
            session,
            settings,
            brand,
            "scripts",
            stem + f"--{row.id}-v{row.version}",
            "\n".join(lines),
            doc,
        )
        return paths
