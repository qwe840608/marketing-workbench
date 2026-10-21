import unicodedata


def has_text(text: str) -> bool:
    value = unicodedata.normalize("NFKC", text).strip()
    # 官方非文字事件存空字串；舊匯入及題庫可能使用顯示用佔位文字。
    return bool(value) and value.casefold() not in {
        "[貼圖]",
        "[sticker]",
        "[圖片]",
        "[image]",
        "[影片]",
        "[video]",
        "[語音]",
        "[音訊]",
        "[audio]",
        "[附件]",
        "[檔案]",
        "[file]",
    }


def message_view(message, name):
    from app.schemas.catalog import MessageView
    from app.schemas.message import MessageContent

    return MessageContent(
        **MessageView.model_validate(message).model_dump(),
        attachments_json=message.attachments_json,
        received_at=message.created_at,
        has_text=has_text(message.text),
        contact_name=(message.sender_name or "品牌方（原生平台）")
        if message.direction == "out"
        else name or "未提供名稱",
    )
