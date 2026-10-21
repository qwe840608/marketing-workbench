"""Read the CSS palette and verify WCAG contrast without dependencies or databases."""

from runtime_tmp import output_dir, runtime_check

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_tokens(css):
    root = re.search(r":root\s*\{([^}]+)\}", css)
    if root is None:
        raise ValueError("Missing :root palette")
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+)", root[1]))


def resolve_color(value, tokens, trail=()):
    value = value.strip()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) != 6:
            raise ValueError(f"Expected opaque color: {value}")
        return tuple(int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))
    alias = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if alias:
        name = alias[1]
        if name in trail:
            raise ValueError(f"Cyclic palette alias: {name}")
        return resolve_color(tokens[name], tokens, (*trail, name))
    mix = re.fullmatch(
        r"color-mix\(in srgb,\s*(var\(--[\w-]+\))\s+([\d.]+)%,\s*(var\(--[\w-]+\))\)",
        value,
    )
    if mix:
        a, b = resolve_color(mix[1], tokens, trail), resolve_color(mix[3], tokens, trail)
        weight = float(mix[2]) / 100
        return tuple(x * weight + y * (1 - weight) for x, y in zip(a, b, strict=True))
    raise ValueError(f"Unsupported palette color: {value}")


def luminance(rgb):
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def contrast(foreground, background):
    a, b = luminance(foreground), luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def check_palette(tokens, css):
    pairs = [
        ("YouTube 延遲指標／權杖狀態／回呼", "--text-subtle", "--bg-surface", 4.5),
        ("YouTube 設定教學連結", "--link-color", "--bg-surface", 4.5),
        ("YouTube Shorts／選文平台／延遲指標", "--text-subtle", "--bg-subtle", 4.5),
        ("YouTube 憑證／訂閱數／成效", "--text-main", "--bg-surface", 4.5),
        ("YouTube 發佈縮圖檔名／格式提示", "--text-subtle", "--bg-surface", 4.5),
        ("YouTube 發佈標題／說明欄位", "--text-main", "--bg-surface", 4.5),
        ("YouTube 發佈「只支援影片」／Shorts 提示底", "--text-subtle", "--bg-subtle", 4.5),
        ("YouTube 預覽標題（粗體）／頻道名稱", "--text-main", "--bg-surface", 4.5),
        ("YouTube 預覽互動列", "--text-subtle", "--bg-surface", 4.5),
        ("YouTube 預覽說明框", "--text-main", "--bg-subtle", 4.5),
        ("YouTube 預覽說明 hashtag", "--link-color", "--bg-subtle", 4.5),
        ("YouTube 縮圖未套用標籤", "--state-pending-text", "--state-pending-bg", 4.5),
        ("YouTube 縮圖失敗原因／重新套用", "--text-main", "--bg-surface", 4.5),
        ("YouTube 連結卡片上傳權限提示／類別", "--text-main", "--bg-surface", 4.5),
        ("YouTube 移除縮圖（危險色按鈕）", "--bg-surface", "--state-danger", 4.5),
        ("限動逐則成效／素材名稱", "--text-main", "--bg-surface", 4.5),
        ("限動則數／成效標籤／FB不可用提示", "--text-subtle", "--bg-surface", 4.5),
        ("限動規格錯誤", "--state-danger", "--bg-surface", 4.5),
        ("限動刪除素材", "--bg-surface", "--state-danger", 4.5),
        ("發佈已連結分頁／預覽選取", "--state-success", "--bg-surface", 4.5),
        ("發佈預覽平台選取", "--brand-primary", "--bg-surface", 4.5),
        ("發佈灰色分頁／頭像", "--text-subtle", "--bg-subtle", 4.5),
        ("發佈預覽正文／段數", "--text-main", "--bg-surface", 4.5),
        ("發佈帳號／未開啟說明", "--text-subtle", "--bg-surface", 4.5),
        ("發佈預覽 @／hashtag／主題標籤", "--link-color", "--bg-surface", 4.5),
        ("發佈超限／紅點", "--state-danger", "--bg-surface", 4.5),
        ("發佈提示", "--state-pending-text", "--bg-subtle", 4.5),
        ("發佈開關反白圓點", "--bg-surface", "--state-success", 3.0),
        ("粉絲工具列數字／選單", "--text-main", "--bg-surface", 4.5),
        ("粉絲工具列標籤／未串接", "--text-muted", "--bg-surface", 4.5),
        ("粉絲工具列無資料", "--text-subtle", "--bg-surface", 4.5),
        ("粉絲工具列正成長", "--state-success", "--bg-surface", 4.5),
        ("粉絲工具列負成長", "--state-danger", "--bg-surface", 4.5),
        ("Claude 桌面版安裝步驟與本機網址提示", "--text-subtle", "--bg-surface", 4.5),
        ("Claude 桌面版網址", "--text-main", "--bg-subtle", 4.5),
        ("Claude 桌面版下載／複製", "--text-main", "--bg-surface", 4.5),
        ("Claude 桌面版選取", "--bg-surface", "--brand-primary", 4.5),
        ("Claude 桌面版未選取", "--text-main", "--bg-surface", 4.5),
        ("Agent 安裝指令", "--text-main", "--bg-subtle", 4.5),
        ("Agent 安裝說明", "--text-subtle", "--bg-surface", 4.5),
        ("Agent 安裝來源提示", "--text-subtle", "--bg-subtle", 4.5),
        ("Agent 安裝來源連結", "--link-color", "--bg-subtle", 4.5),
        ("Agent 安裝複製／下載", "--text-main", "--bg-surface", 4.5),
        ("Agent 安裝類型選取", "--bg-surface", "--brand-primary", 4.5),
        ("Agent 安裝類型未選取", "--text-main", "--bg-surface", 4.5),
        ("Agent 報告／腳本來源膠囊", "--text-subtle", "--bg-subtle", 4.5),
        ("Agent 等待存回說明", "--text-subtle", "--bg-surface", 4.5),
        ("Agent 核准資訊／連線名稱／次要操作", "--text-main", "--bg-surface", 4.5),
        ("Agent 回呼標籤／連線日期／成員連線數", "--text-subtle", "--bg-surface", 4.5),
        ("Agent 一次性權杖", "--text-main", "--bg-subtle", 4.5),
        ("Agent 核准", "--bg-surface", "--brand-primary", 4.5),
        ("Agent 撤銷／確認", "--bg-surface", "--state-danger", 4.5),
        ("Agent 連線類型", "--text-subtle", "--bg-subtle", 4.5),
        ("編輯主題欄位", "--text-main", "--bg-surface", 4.5),
        ("已編輯主題膠囊", "--text-subtle", "--bg-subtle", 4.5),
        ("卡片序號", "--text-subtle", "--bg-surface", 4.5),
        ("卡片查看腳本／建立發佈草稿（secondary）", "--text-main", "--bg-surface", 4.5),
        ("交給 Agent 撰寫 接手說明", "--text-subtle", "--bg-surface", 4.5),
        ("舊 CLI 報告錯誤說明", "--state-danger", "--bg-subtle", 4.5),
        ("草稿文案與媒體", "--text-main", "--bg-surface", 4.5),
        ("主題草稿次要動作", "--text-main", "--bg-surface", 4.5),
        ("主題草稿來源膠囊", "--text-subtle", "--bg-subtle", 4.5),
        ("主題草稿建立成功提示", "--state-success", "--bg-subtle", 4.5),
        ("發佈步驟序號", "--bg-surface", "--brand-primary", 4.5),
        ("發佈規則失敗原因", "--state-danger", "--bg-surface", 4.5),
        ("發佈媒體尺寸／帳號", "--text-subtle", "--bg-surface", 4.5),
        ("發佈關閉提示", "--state-pending-text", "--state-pending-bg", 4.5),
        ("發佈成功結果", "--state-success", "--state-success-bg", 4.5),
        ("發佈紀錄上次檢查文字", "--text-subtle", "--bg-app", 4.5),
        ("發佈紀錄刪除偵測時間", "--text-main", "--bg-surface", 4.5),
        ("發佈失敗結果", "--state-danger", "--state-danger-bg", 4.5),
        ("OAuth 帳號／首次設定步驟／進階摘要", "--text-main", "--bg-surface", 4.5),
        ("OAuth 回呼網址／到期時間", "--text-subtle", "--bg-surface", 4.5),
        ("OAuth 來源提示／連結", "--link-color", "--bg-subtle", 4.5),
        ("OAuth 成功提示／已連結", "--state-success", "--state-success-bg", 4.5),
        ("OAuth 缺權限／失敗", "--state-danger", "--state-danger-bg", 4.5),
        ("OAuth 即將到期", "--state-pending-text", "--state-pending-bg", 4.5),
        ("共用中性狀態 .status-badge.neutral", "--text-subtle", "--bg-subtle", 4.5),
        ("共用錯誤提示 .notice.danger／.error", "--state-danger", "--bg-subtle", 4.5),
        ("底線分頁未選文字", "--text-subtle", "--bg-app", 4.5),
        ("底線分頁選中文字與底線", "--brand-primary", "--bg-app", 4.5),
        ("Obsidian 次要同步", "--text-main", "--bg-surface", 4.5),
        ("發想步驟圓標", "--bg-surface", "--brand-primary", 4.5),
        ("平台分頁／hover", "--brand-primary", "--bg-subtle", 4.5),
        ("提示框／匯出膠囊／留言作者時間", "--text-subtle", "--bg-subtle", 4.5),
        ("留言預覽正文", "--text-main", "--bg-subtle", 4.5),
        ("發想計時器", "--text-subtle", "--bg-surface", 4.5),
        ("發想次要動作", "--text-main", "--bg-surface", 4.5),
        ("發想次要動作 hover／貼文標題列／選中報告", "--text-main", "--bg-subtle", 4.5),
        ("發想摘要／貼文日期", "--text-subtle", "--bg-surface", 4.5),
        ("貼文平台膠囊／標題列合計", "--text-subtle", "--bg-subtle", 4.5),
        ("範圍內非零留言數／hover", "--brand-primary", "--bg-subtle", 4.5),
        ("完成狀態／變現型膠囊", "--state-success", "--state-success-bg", 4.5),
        ("失敗狀態膠囊", "--state-danger", "--state-danger-bg", 4.5),
        ("進行中狀態／引流型膠囊", "--state-pending-text", "--state-pending-bg", 4.5),
        ("流量型膠囊", "--state-info", "--state-info-bg", 4.5),
        ("三類分組色條旁標題", "--text-main", "--bg-app", 4.5),
        ("三類分組色條旁題數", "--text-muted", "--bg-app", 4.5),
        ("留言範圍選取", "--bg-surface", "--brand-primary", 4.5),
        ("留言範圍未選取", "--text-subtle", "--bg-surface", 4.5),
        ("留言日期／範圍內已存數", "--text-muted", "--bg-surface", 4.5),
        ("主題卡片／刪除視窗", "--text-main", "--bg-surface", 4.5),
        ("貼文日期／留言數／主題分類", "--text-muted", "--bg-surface", 4.5),
        ("主題類型／元素／延伸主題／關鍵字", "--text-subtle", "--bg-subtle", 4.5),
        ("主題分組題數", "--text-muted", "--bg-app", 4.5),
        ("主題列表刪除／確認", "--bg-surface", "--state-danger", 4.5),
        ("報告取消", "--bg-surface", "--brand-primary", 4.5),
        ("貼文勾選", "--brand-primary", "--bg-surface", 3.0),
        ("新留言 KPI／空分類", "--text-main", "--bg-surface", 4.5),
        ("每日新留言空資料", "--text-muted", "--bg-surface", 4.5),
        ("平台憑證名稱／輸入／工作區分組", "--text-main", "--bg-surface", 4.5),
        ("平台憑證遮罩", "--text-subtle", "--bg-surface", 4.5),
        ("供應商遮罩／備援模型淡底", "--text-subtle", "--bg-subtle", 4.5),
        ("平台來源標籤", "--state-success", "--state-success-bg", 4.5),
        ("平台主要動作", "--bg-surface", "--brand-primary", 4.5),
        ("平台唯讀／env 說明", "--text-muted", "--bg-surface", 4.5),
        ("平台操作錯誤", "--state-danger", "--state-danger-bg", 4.5),
        ("主題發想歷史原話標示", "--text-main", "--bg-surface", 4.5),
        ("報告刪除按鈕", "--text-muted", "--bg-surface", 4.5),
        ("報告刪除按鈕 hover／標題", "--text-main", "--bg-surface", 4.5),
        ("報告刪除錯誤", "--state-danger", "--state-danger-bg", 4.5),
        ("自動啟動標題／開關", "--text-main", "--bg-surface", 4.5),
        ("自動啟動說明／處理中／不支援", "--text-muted", "--bg-surface", 4.5),
        ("自動啟動錯誤", "--state-danger", "--state-danger-bg", 4.5),
        ("自動啟動勾選", "--brand-primary", "--bg-surface", 3.0),
        ("每日趨勢標題／控制項", "--text-main", "--bg-surface", 4.5),
        ("每日趨勢軸／圖例／空資料", "--text-muted", "--bg-surface", 4.5),
        ("每日趨勢提示", "--text-subtle", "--bg-subtle", 4.5),
        ("每日趨勢選取天數", "--bg-surface", "--brand-primary", 4.5),
        ("每日趨勢錯誤", "--state-danger", "--state-danger-bg", 4.5),
        ("每日趨勢長條", "--brand-primary", "--bg-surface", 3.0),
        ("每日趨勢焦點", "--focus-ring", "--bg-surface", 3.0),
        ("精簡 KPI／品牌說明／工作區進階摘要", "--text-main", "--bg-surface", 4.5),
        ("預設 AI／類別說明／內容指示／主題發想執行方式", "--text-main", "--bg-surface", 4.5),
        ("主要按鈕", "--bg-surface", "--brand-primary", 4.5),
        ("刪除報告／確認刪除（危險色按鈕）", "--bg-surface", "--state-danger", 4.5),
        ("內文／表面", "--text-main", "--bg-surface", 4.5),
        ("內文／畫布", "--text-main", "--bg-app", 4.5),
        ("輔助文字／表面", "--text-muted", "--bg-surface", 4.5),
        ("輔助文字／畫布", "--text-muted", "--bg-app", 4.5),
        ("淡底文字／淡底", "--text-subtle", "--bg-subtle", 4.5),
        ("主要按鈕", "--bg-surface", "--brand-primary", 4.5),
        ("主要按鈕 hover", "--bg-surface", "--brand-hover", 4.5),
        ("側欄文字", "--sidebar-text", "--brand-primary", 4.5),
        ("側欄輔助文字", "--sidebar-muted", "--brand-primary", 4.5),
        ("側欄選取文字", "--sidebar-text", "--sidebar-selected", 4.5),
        ("側欄選取輔助文字", "--sidebar-muted", "--sidebar-selected", 4.5),
        ("反白危險警示", "--bg-surface", "--state-danger", 4.5),
        ("連結", "--link-color", "--bg-surface", 4.5),
        ("連結／淡底", "--link-color", "--bg-subtle", 4.5),
        ("一般狀態／淡底", "--text-subtle", "--bg-subtle", 4.5),
        ("一般狀態／白底", "--text-subtle", "--bg-surface", 4.5),
        ("儀表板長條／軌道", "--brand-primary", "--bg-subtle", 3.0),
        ("分流設定卡片標題與欄位", "--text-main", "--bg-surface", 4.5),
        ("分流設定卡片輔助文字", "--text-muted", "--bg-surface", 4.5),
        ("分流設定門檻說明", "--text-muted", "--bg-app", 4.5),
        ("類別說明標籤與輸入", "--text-main", "--bg-surface", 4.5),
        ("類別說明預設提示", "--text-muted", "--bg-surface", 4.5),
        ("類別說明儲存", "--bg-surface", "--brand-primary", 4.5),
        ("類別說明錯誤", "--state-danger", "--state-danger-bg", 4.5),
        ("AI 頁籤", "--text-main", "--bg-surface", 4.5),
        ("AI 頁籤 hover", "--text-main", "--bg-subtle", 4.5),
        ("AI 選取頁籤", "--bg-surface", "--brand-primary", 4.5),
    ]
    pairs.extend([
        ("members 名稱／表單／臨時密碼", "--text-main", "--bg-surface", 4.5),
        ("members 帳號／品牌／帳號摘要", "--text-subtle", "--bg-surface", 4.5),
        ("members 臨時密碼淡底", "--text-main", "--bg-subtle", 4.5),
        ("members 角色／停用", "--text-subtle", "--bg-subtle", 4.5),
        ("members 啟用", "--state-success", "--state-success-bg", 4.5),
        ("members 須改密碼", "--state-pending-text", "--state-pending-bg", 4.5),
        ("members 保護錯誤", "--state-danger", "--bg-subtle", 4.5),
        ("members 儲存成功", "--state-success", "--bg-subtle", 4.5),
        ("members 密碼說明", "--text-muted", "--bg-surface", 4.5),
        ("Obsidian 欄位／卡片選取序號", "--text-main", "--bg-surface", 4.5),
        ("Obsidian 儲存同步", "--bg-surface", "--brand-primary", 4.5),
        ("卡片舊重新生成／延伸自標記", "--text-subtle", "--bg-subtle", 4.5),
        ("Obsidian／卡片失敗", "--state-danger", "--state-danger-bg", 4.5),
        ("所選留言重新標註", "--text-main", "--bg-surface", 4.5),
        ("所選留言重算結果", "--state-success", "--state-success-bg", 4.5),
        ("前期發佈時間提示", "--text-main", "--bg-surface", 4.5),
        ("全期留言抓取說明", "--text-muted", "--bg-surface", 4.5),
        ("舊 CLI 用量紀錄／未回報／訂閱", "--text-main", "--bg-surface", 4.5),
        ("舊 CLI 用量紀錄／桌面／未回報／訂閱", "--text-main", "--bg-app", 4.5),
        ("設定選取分頁", "--bg-surface", "--brand-primary", 4.5),
        ("設定分頁與手機品牌", "--text-main", "--bg-surface", 4.5),
        ("設定分頁 hover", "--text-main", "--bg-subtle", 4.5),
        ("設定手機登出", "--text-muted", "--bg-app", 4.5),

        ("手機導覽未選取", "--text-main", "--bg-surface", 4.5),
        ("手機導覽選取與數量／更多動作", "--bg-surface", "--brand-primary", 4.5),
        ("更多動作 hover", "--bg-surface", "--brand-hover", 4.5),
        ("更多品牌標籤與選單", "--text-main", "--bg-surface", 4.5),
        ("更多關閉與登出", "--text-muted", "--bg-surface", 4.5),
    ])
    for name, foreground, background in (
        ("待處理／警告", "--state-pending-text", "--state-pending-bg"),
        ("錯誤／需修改", "--state-danger", "--state-danger-bg"),
        ("成功／已回覆", "--state-success", "--state-success-bg"),
        ("處理中", "--state-info", "--state-info-bg"),
    ):
        for label, bg in (("淡底", background), ("白底", "--bg-surface"), ("畫布", "--bg-app")):
            pairs.append((f"{name}／{label}", foreground, bg, 4.5))
    for token in (
        "--focus-ring", "--state-danger", "--state-success",
        "--chart-line", "--chart-point", "--chart-intent",
    ):
        pairs.append((f"圖示／線條 {token}", token, "--bg-surface", 3.0))
    rows = []
    pairs.append(("發佈 Agent 草稿／紀錄來源膠囊", "--text-subtle", "--bg-subtle", 4.5))
    # Threads：設定頁「需要重新連結以取得數據與回覆權限」警告提示（淡底、琥珀左線，文字為輔助色）。
    pairs.append(("Threads 數據與回覆權限提示 .notice.warning", "--text-subtle", "--bg-subtle", 4.5))
    # 存成 FB 草稿：勾選框文字、確認視窗摘要，以及發佈紀錄的中性灰「成功 · 草稿」膠囊。
    pairs.append(("發佈存成 FB 草稿勾選框／確認摘要", "--text-main", "--bg-surface", 4.5))
    pairs.append(("發佈紀錄 Facebook 草稿膠囊", "--text-subtle", "--bg-subtle", 4.5))
    # 每日趨勢只保留長條；驗證實際圖形與鍵盤焦點的對比。
    pairs.append(("每日趨勢長條", "--brand-primary", "--bg-surface", 3.0))
    pairs.append(("每日趨勢鍵盤焦點", "--focus-ring", "--bg-surface", 3.0))
    # 平台設定教學視窗：白底標題與步驟、淡底網址／權限區塊，以及連線卡片的中性膠囊（例如未連結）。
    pairs.extend([
        ("平台教學視窗標題／步驟／次要按鈕", "--text-main", "--bg-surface", 4.5),
        ("平台教學視窗網址／權限區塊", "--text-subtle", "--bg-subtle", 4.5),
        ("連線卡片中性膠囊", "--text-subtle", "--bg-subtle", 4.5),
        # guides3 精簡版：步驟編號方塊、直達連結、完成後會看到（.notice.success）、收合的常見問題。
        ("平台教學步驟編號方塊", "--bg-surface", "--brand-primary", 4.5),
        ("平台教學直達連結", "--link-color", "--bg-surface", 4.5),
        ("平台教學「完成後會看到」.notice.success", "--state-success", "--bg-subtle", 4.5),
        ("平台教學常見問題", "--text-subtle", "--bg-subtle", 4.5),
    ])
    pairs.extend([
        ("uniform2 工作區 summary／小節", "--text-main", "--bg-surface", 4.5),
        ("uniform2 收合圖示／貼文日期／平台膠囊", "--text-subtle", "--bg-subtle", 4.5),
        ("uniform2 選中貼文色條", "--brand-primary", "--bg-subtle", 3.0),
        ("uniform2 全域手機品牌文字", "--text-main", "--bg-app", 4.5),
        ("uniform2 實心動作／目前手機頁", "--bg-surface", "--brand-primary", 4.5),
        ("uniform2 手機憑證名稱", "--text-main", "--bg-surface", 4.5),
    ])
    for name, fg, bg, minimum in pairs:
        ratio = contrast(resolve_color(tokens[fg], tokens), resolve_color(tokens[bg], tokens))
        rows.append({
            "name": name, "foreground": fg, "background": bg,
            "ratio": ratio, "minimum": minimum, "passed": ratio >= minimum,
        })
    return rows


@runtime_check
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--css", type=Path, default=ROOT / "frontend/src/style.css")
    parser.add_argument("--output", type=Path, default=output_dir() / "report.json")
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / ".runtime").resolve()):
        parser.error("Acceptance output must be inside .runtime/")
    css = args.css.read_text(encoding="utf-8")
    rows = check_palette(read_tokens(css), css)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        print(
            f"{'PASS' if row['passed'] else 'FAIL'} {row['name']}: "
            f"{row['ratio']:.3f}:1 >= {row['minimum']}:1"
        )
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
