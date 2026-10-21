"""由 check_ui_scale 的隔離後端與尺寸量測器執行真實 CSV UI 流程。"""


def exercise_csv(page, width, height, capture):
    from playwright.sync_api import expect

    section = page.get_by_role("region", name="匯入歷史資料")
    section.scroll_into_view_if_needed()
    payload = (
        "platform,kind,external_id,conversation_id,created_at,author,content,source_ref\n"
        f"FB,comment,csv-ui-{width},csv-thread-{width},2026-09-20 09:30:00,"
        "[隔離驗收] 測試客人,[隔離驗收] 歷史詢問,歷史.csv：第2列\n"
        f"FB,comment,csv-ui-{width},csv-thread-{width},2026-09-20 09:30:00,"
        "[隔離驗收] 測試客人,[隔離驗收] 歷史詢問,歷史.csv：第3列\n"
        "FB,comment,csv-invalid,csv-invalid,無效日期,測試客人,錯誤列保留原因,歷史.csv：第4列\n"
    )
    section.get_by_label("歷史資料檔案").set_input_files(
        {"name": "隔離歷史.csv", "mimeType": "text/csv", "buffer": payload.encode("utf-8-sig")}
    )
    section.get_by_role("button", name="讀取 CSV 欄位").click()
    expect(section.get_by_role("heading", name="欄位對應 · 共 3 列")).to_be_visible()
    section.get_by_role("heading", name="欄位對應 · 共 3 列").scroll_into_view_if_needed()
    capture("csv-mapping", width, height)
    select = section.locator('select[aria-label$="匯入帳號"]').filter(
        has=page.locator('option', has_text="[隔離驗收] FB")
    )
    option = select.locator("option").nth(1).get_attribute("value")
    select.select_option(option)
    section.get_by_role("button", name="驗證並預覽資料").click()
    expect(section.get_by_role("heading", name="匯入前預覽")).to_be_visible()
    expect(section.get_by_text("第 4 列：時間無法解析", exact=False)).to_be_visible()
    section.get_by_role("heading", name="匯入前預覽").scroll_into_view_if_needed()
    capture("csv-preview", width, height)
    section.get_by_role("checkbox", name="我已核對品牌、帳號與資料，僅匯入有效列").check()
    section.get_by_role("button", name="確認匯入歷史資料").click()
    expect(section.get_by_text("新增 1 列、重複略過 1 列、錯誤 1 列。")).to_be_visible()
    section.get_by_role("heading", name="匯入完成").scroll_into_view_if_needed()
    capture("csv-completed", width, height)
