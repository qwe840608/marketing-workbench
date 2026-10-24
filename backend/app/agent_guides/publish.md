# 發佈、排程與重試

1. get_server_info、get_brand_guide、get_publish_options，確認品牌規範、總開關及帳號。檢視者只讀；存草稿需要 `publish.edit`，確認發佈、重試、取消排程需要 `publish.submit`（見 `get_server_info` 的 `user.permissions`）；總開關關閉只能存草稿，請管理員在網頁處理，不代改開關。
2. 一般貼文先 get_guide("post") 完成定案文案、存草稿與上傳；限時動態用 save_publish_draft(format="story", platforms=["facebook", "instagram"]) 建空白草稿，caption 省略或空字串，沿既有上傳碼流程上傳 1–10 張圖／影片，一則一份素材。限動不能帶文字、captions、platform_options、未公開選項或 Threads；media_ids 可傳完整既有素材排序。get_publish_post 取得 version 與各平台 checks，所有選定平台須符合規則且帳號就緒。
3. 詢問使用者立即發佈或台北排程時間；prepare_publish(post_id, version, scheduled_at?) 不送出。時間須含時區（+08:00）且在一分鐘後，省略代表立即。
4. **完整呈現** details：品牌、每個平台帳號名稱、限動的 story_count／各平台接續進度／素材順序（沒有文案），一般貼文的主文案全文、平台覆寫全文、平台選項與實際生效選項、Threads 各段全文及已成功段數、提示、媒體檔名／型別／大小／尺寸／長度、立即或 +08:00 時間、是否只重試失敗平台。不得省略截斷；truncated 時禁止確認，縮短草稿後重新準備。details.facebook_unpublished 為 true 時，必須明確告知「Facebook 會存成草稿不發佈（可在 Meta Business Suite 草稿匣編輯後再發）（Instagram／Threads 照常公開）」。confirmation_code 是授權秘密，不必顯示給使用者。
5. **一定詢問並等待使用者明確同意**，例如「確認發佈」。不得把沉默、先前存草稿／上傳、對文案的認可或查詢當成發佈同意，不得自行假設同意。
6. 同意後才 confirm_publish(post_id, confirmation_code)。碼綁定成員、草稿、版本、明細雜湊，10 分鐘一次性。內容、平台選項、Threads 分段／進度、媒體內容／排序、限動成功則數、帳號、狀態或版本改動，過期／重放／別人成員使用、總開關關閉，一律重新 prepare_publish、完整呈現並再次取得同意，不自動重試確認。
7. get_publish_post 查狀態與各平台結果／連結，限動可讀逐則 IG 成效及 final，缺值維持未知，FB 不提供限動成效；publishing 時稍後再查，不重複送出。排程尚未送出，不把草稿或排程說成已發佈。

取消排程先詢問，cancel_schedule 回草稿；發佈前一分鐘鎖定後不可取消。改時間、文案或媒體先取消，save_publish_draft 後重新兩段式確認。已送出不可修改或刪除。

失敗／部分成功先告知各平台結果，逾時或中斷請使用者到平台確認是否已發佈，避免重複。retry_failed_platforms(post_id, version) 等同 prepare_publish(retry=true)，只準備失敗平台，成功平台永不重送，限動依成功則數只接續失敗那則與後續素材，已有成功則時素材不可修改；完整呈現、明確同意後才 confirm_publish。重新排程可 prepare_publish(retry=true, scheduled_at=...)。

文案可以用 Markdown（# 大標題、## 小標題、**粗體**、*斜體*、- 項目、1. 編號）。平台不支援 Markdown，發佈時工作檯會自動轉成純文字：# 大標題變「█ 大標題」、## 小標題變「▍小標題」、粗體與斜體的英文與數字轉成 Unicode 字形（中文只去掉符號）、- 項目變 •、編號不變；platform_captions 空白或只有空白字元時沿用共用文案。字數與 hashtag 規則依轉換後的文字檢查；prepare_publish 明細的 sent_captions 列出轉換後與原稿不同的平台實際送出的文字，呈現給使用者確認時以它為準。

facebook_unpublished 只在使用者明確要求「存成 FB 草稿」時才設為 true（預設 false，只影響 Facebook；更新草稿時省略代表沿用原值）；改了選項要重新 prepare_publish 並再次取得同意，已送出不可更改。

save_publish_draft 的 platform_options 可局部設定 facebook.video_format（feed／reels）、instagram.share_to_feed（布林）、threads.segments（字串陣列）及 threads.segments_custom（布林），更新時省略欄位沿用原值。新影片草稿 Facebook 預設 reels，既有資料維持 feed；IG 預設 true。facebook_unpublished=true 時 Facebook 實際改用 feed，完整呈現此差異。

Threads 每段最多 500 計數單位，emoji 按 UTF-8 位元組計數；分段不加任何編號。segments_custom=false 時儲存會依 Threads 專屬文案或主文案自動重算，優先空行／換行、其次句號、最後硬切；傳入 segments 而省略 segments_custom 視為手動編輯。多個 hashtag 不阻擋，只使用第一個當主題標籤。素材只附第一段，各段回覆前一段；部分失敗重試只接續未成功段落，確認時須呈現進度與剩餘內容。已成功／發佈中的平台選項與已有成功段落的 Threads 分段不可更改，取消／重新排程也保留。

YouTube：platforms 可含 youtube，只支援 format=video。platform_options.youtube 可設 title（空白或省略沿用說明第一行，≤100 字）、privacy（public／unlisted／private，預設 public）、made_for_kids（布林，預設 false）；說明用 platform_captions.youtube（≤5000 位元組）。自訂縮圖用 create_upload_link(role="thumbnail") 上傳 JPG／PNG（2 MB 內，僅影片草稿，不算素材），不能直接指定縮圖編號；直式或正方形且 3 分鐘內的影片會被 YouTube 歸為 Shorts，Shorts 不支援自訂縮圖。呈現 details.youtube 時必須列出標題、公開狀態（public 代表上傳後立即公開）、兒童內容聲明與是否有縮圖；改了標題、公開狀態、兒童內容或縮圖要重新 prepare_publish 並再次取得同意。縮圖失敗不影響影片成功：get_publish_post 的 detail.thumbnail 回 status 與原因，請使用者到網頁發佈紀錄按「重新套用縮圖」，不要重送影片。

Instagram Reels 封面：format=video 時可用 create_upload_link(role="cover") 上傳 JPG／PNG（8 MB 內，建議 9:16，非 9:16 會被裁切中間），不算素材，新的取代舊的；沒有封面時 Instagram 用影片第一格。呈現 details.instagram 時必須說明有沒有自訂封面；換了封面要重新 prepare_publish 並再次取得同意。Instagram 已發佈後不能更換封面。

Facebook 影片／Reels 封面：format=video 時可用 create_upload_link(role="fb_cover") 上傳 JPG／PNG（8 MB 內，建議與影片同比例），不算素材，新的取代舊的。封面在影片成功後才另外套用，失敗不影響貼文：get_publish_post 的 Facebook 目標 detail.cover 回 status 與原因，請使用者到網頁發佈紀錄按「重新套用封面」，不要重送影片。需要 pages_manage_engagement 權限，get_publish_options 的 platforms.facebook.cover_hint 有值代表缺少，請管理員重新連結 Meta。呈現 details.facebook 時必須說明有沒有自訂封面；換了封面要重新 prepare_publish 並再次取得同意。

TikTok：platforms 可含 tiktok，只支援 format=video（最長 10 分鐘、長寬 360–4096 px），沒有 platform_options。影片只會送到使用者的 TikTok 收件匣，不會直接公開；TikTok 的收件匣 API 不收文案，platform_captions.tiktok 只留在工作檯供使用者複製。呈現 details.tiktok 時必須說明「只送到收件匣、文案不會送出，需在 TikTok App 內貼上文案並按發佈」。成功後 get_publish_post 的 detail.inbox_state 是 SEND_TO_USER_INBOX（已送到收件匣），使用者在 App 發佈後會變成 PUBLISH_COMPLETE；收件匣 24 小時內最多 5 支待處理，超過時發佈失敗（inbox_full），請使用者先在 App 處理再重試。圖文不支援，請使用者從 TikTok App 上傳。送到收件匣後 TikTok 仍可能回報失敗，get_publish_post 的 TikTok 目標會變成 failed 並帶 error_code：只有 platform_busy（TikTok 暫時故障）適合重試；posting_limited、posting_banned、spam_risk、token_invalid、media_rejected 重試也會再被拒，告知使用者原因（帳號受限、需重新連結或換影片），不要建議重試。重試不會重複上傳已完成的影片。TikTok 官方沒有保證收件匣影片在 App 發佈後一定公開：提醒使用者在 App 發佈畫面選「所有人」，發佈後用未登入的瀏覽器開影片連結確認，或等下一輪每小時同步後看貼文頁的 TikTok 分頁是否出現（同步只會抓到公開影片）。

版本衝突重讀；規則不符修正草稿；未就緒請管理員連結平台。跨品牌視為不存在。發佈授權不等於修改設定或回覆訊息的授權。
