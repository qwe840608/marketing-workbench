// 各平台的設定教學內容；視窗只負責呈現，內容集中在這裡方便維護與測試。
// 寫法：每步一句話、只講要點；要去別的平台時附上直達連結，卡關說明集中放在最後的「常見問題」。
// 網址類值不寫死：回呼網址與 Webhook 網址由設定頁提供的資料在顯示時帶入。
import { t } from './i18n.ts';

export type GuideValue =
  | { kind: 'text'; value: string }
  | { kind: 'callback'; platform: 'meta' | 'threads' | 'youtube' | 'tiktok' }
  | { kind: 'webhook'; path: string };
// links：直達平台後台的超連結（新分頁開啟）；check：做完這步會看到什麼。
export type GuideLink = { label: string; url: string };
export type GuideStep = { text: string; links?: GuideLink[]; values?: GuideValue[]; check?: string };
export type GuideSection = { heading?: string; steps: GuideStep[] };
export type PlatformGuide = { id: GuideId; title: string; minutes: number; needs: string[]; faq: string[]; sections: GuideSection[] };
export type GuideId = 'meta' | 'threads' | 'youtube' | 'notify' | 'jev' | 'webhook' | 'tiktok';
export type GuideContext = { callbacks?: Record<string, string>; webhookUrl?: string };

const text = (value: string): GuideValue => ({ kind: 'text', value });
const callback = (platform: 'meta' | 'threads' | 'youtube' | 'tiktok'): GuideValue => ({ kind: 'callback', platform });
const link = (label: string, url: string): GuideLink => ({ label, url });

export const facebookPermissions = ['pages_show_list', 'pages_read_engagement', 'pages_read_user_content', 'pages_manage_metadata', 'pages_manage_posts', 'read_insights'];
export const instagramPermissions = ['instagram_basic', 'instagram_manage_comments', 'instagram_manage_insights', 'instagram_content_publish'];
export const threadsPermissions = ['threads_basic', 'threads_content_publish', 'threads_manage_replies', 'threads_manage_insights', 'threads_read_replies'];
export const tiktokScopes = ['user.info.basic', 'user.info.stats', 'video.list', 'video.upload'];
// 留言只有 TikTok API for Business 提供，而它只收公司身分的開發者；教學、卡片與貼文數據共用同一句。
export const tiktokCommentNotice = t('讀取 TikTok 留言需要以公司身分申請 TikTok API for Business（個人開發者無法申請）');
export const youtubeScopes = ['https://www.googleapis.com/auth/youtube.readonly', 'https://www.googleapis.com/auth/yt-analytics.readonly', 'https://www.googleapis.com/auth/youtube.upload'];

// 教學裡允許出現的外部網域；測試會檢查每個連結都在清單內且是 https。
export const guideLinkHosts = ['developers.facebook.com', 'console.cloud.google.com', 'manager.line.biz', 'developers.line.biz', 'developers.tiktok.com', 'console.typesafe.ai', 'dashboard.ngrok.com'];

const metaApps = link(t('開啟 Meta 開發者後台'), 'https://developers.facebook.com/apps/');
const internalHttps = t('用內部 https 網址（網址開頭是 https://）開啟本工作檯');
const originFaq = t('「連結」按鈕是灰色：改用內部 https 網址重新開啟工作檯。');

export const platformGuides: Record<GuideId, PlatformGuide> = {
  meta: {
    id: 'meta',
    title: t('Facebook 粉專與 Instagram 設定教學'),
    minutes: 20,
    needs: [t('你是該 Facebook 粉專的管理員'), t('Instagram 要是專業帳號並連到該粉專（沒有 Instagram 可略過）'), internalHttps],
    faq: [
      t('授權時找不到粉專：重按「連結 Meta 帳號」，在授權畫面按「編輯設定」（新版畫面可能叫「編輯存取權限」）把粉專勾起來；你也必須是該粉專的管理員。'),
      t('出現「網址不符」：回呼網址要用複製鈕整串貼上，不可多斜線或改成 http。'),
      t('畫面要你輸入 Facebook 密碼：這是 Meta 的安全確認，輸入自己的密碼即可。'),
      t('Instagram 選不到粉專：登入 Instagram 的人也必須是這個粉專的管理員。'),
      originFaq,
    ],
    sections: [
      {
        heading: t('Facebook 粉專'),
        steps: [
          { text: t('開 Meta 開發者後台，按「建立應用程式」，名稱隨意；使用案例選跟粉絲專頁有關的項目，其餘一路按「下一步」。'), links: [link(t('建立應用程式'), 'https://developers.facebook.com/apps/creation/')] },
          { text: t('左側「應用程式設定 → 基本資料」，把「應用程式編號」和「應用程式密鑰」分別貼到工作檯 Meta 卡片的「應用程式 ID」與「應用程式密鑰」。'), links: [metaApps], check: t('工作檯兩個欄位都改顯示遮蔽過的內容。') },
          { text: t('左側「Facebook 登入 → 設定」（使用案例流程建立的應用程式叫「企業版 Facebook 登入 → 設定」）的「有效的 OAuth 重新導向 URI」貼上這串網址，按「儲存變更」。'), values: [callback('meta')] },
          { text: t('「使用案例 → 自訂 → 權限和功能」，下列權限要一個一個找到後按「新增」（Meta 沒有一次全部新增的功能；可按複製，再用 Ctrl+F 在頁面上搜尋）。'), values: facebookPermissions.map(text) },
        ],
      },
      {
        heading: t('Instagram（沒有 Instagram 可略過）'),
        steps: [
          { text: t('同一頁再把下列 Instagram 權限一個一個按「新增」；同一頁找不到時，回「使用案例」新增 Instagram 的使用案例（管理 Instagram 上的訊息和內容），選「透過 Facebook 登入設定 API」後再新增。'), values: instagramPermissions.map(text) },
        ],
      },
      {
        heading: t('連結帳號'),
        steps: [
          { text: t('回到工作檯按「連結 Meta 帳號」，在授權畫面按「編輯設定」（或「編輯存取權限」）勾選粉專（和 Instagram），再按「繼續」。看到「已連結」就完成，資料約每小時同步一次。'), check: t('Meta 卡片顯示粉專名稱與「已連結」。') },
        ],
      },
    ],
  },
  threads: {
    id: 'threads',
    title: t('Threads 設定教學'),
    minutes: 15,
    needs: [t('一個 Threads 帳號，手機 Threads App 已登入'), t('已有 Meta 應用程式（沒有就照 Facebook 教學第 1 步建立）'), internalHttps],
    faq: [
      t('授權畫面說你不是測試人員：到手機 Threads App 確認已按「接受」邀請。'),
      t('看不到邀請：確認輸入的是 Threads 帳號名稱，並把 Threads App 完全關閉再重開。'),
      t('出現「網址不符」：回呼網址要用複製鈕整串貼上。'),
      originFaq,
    ],
    sections: [{
      steps: [
        { text: t('開 Meta 開發者後台打開你的應用程式，在「使用案例」新增「存取 Threads API」，點「自訂 → 設定」。'), links: [metaApps] },
        { text: t('把「Threads 應用程式編號」和「Threads 應用程式密鑰」貼到工作檯 Threads 卡片（和 Facebook 的不是同一組）。'), check: t('工作檯兩個欄位都改顯示遮蔽過的內容。') },
        { text: t('同一頁的「重新導向回呼網址」貼上這串網址並儲存。'), values: [callback('threads')] },
        { text: t('「權限和功能」把下列權限一個一個按「新增」（沒有一次全部新增的功能；threads_basic 是必要權限，已預設加入）。'), values: threadsPermissions.map(text) },
        { text: t('「應用程式角色 → 角色 → 新增用戶」，選「Threads 測試人員」，輸入你的 Threads 帳號名稱。') },
        { text: t('手機 Threads App（或 Threads 網站）「設定 → 帳號 → 網站權限 → 邀請」，按「接受」。') },
        { text: t('回到工作檯按「連結 Threads 帳號」並同意授權。看到「已連結」就完成，資料約每小時同步一次。'), check: t('Threads 卡片顯示帳號名稱與「已連結」。') },
      ],
    }],
  },
  youtube: {
    id: 'youtube',
    title: t('YouTube 設定教學'),
    minutes: 15,
    needs: [t('擁有（或管理）該 YouTube 頻道的 Google 帳號'), internalHttps],
    faq: [
      t('出現「Google 尚未驗證這個應用程式」：這是你自己建立的，按「進階」→「前往（應用程式名稱）（不安全）」。'),
      t('授權大約每 7 天失效：「目標對象」的發布狀態要改成「實際運作中」，改完後重新連結一次（測試期間取得的授權仍會在 7 天後失效）。'),
      t('頻道屬於品牌帳戶：選帳號時選那個品牌頻道，不要選個人頻道。'),
      t('出現「redirect_uri_mismatch」：重新導向 URI 要用複製鈕整串貼上。'),
      t('卡片顯示缺少權限：重新連結，權限畫面全部勾選。'),
      originFaq,
    ],
    sections: [{
      steps: [
        { text: t('建立 Google Cloud 專案，名稱隨意。'), links: [link(t('建立專案'), 'https://console.cloud.google.com/projectcreate')] },
        { text: t('啟用 YouTube Data API v3 與 YouTube Analytics API（兩個都按「啟用」）。'), links: [link('YouTube Data API v3', 'https://console.cloud.google.com/apis/library/youtube.googleapis.com'), link('YouTube Analytics API', 'https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com')] },
        { text: t('「品牌」按「開始使用」，填應用程式名稱與使用者支援電子郵件；「目標對象」選「外部」，填聯絡 Email、勾選同意後按「建立」；再到「目標對象」按「發布應用程式」改成「實際運作中」。'), links: [link(t('品牌'), 'https://console.cloud.google.com/auth/branding'), link(t('目標對象'), 'https://console.cloud.google.com/auth/audience')] },
        { text: t('「資料存取權」按「新增或移除範圍」，在「手動新增範圍」貼上這三行，按「新增至資料表」→「更新」→「儲存」。'), links: [link(t('資料存取權'), 'https://console.cloud.google.com/auth/scopes')], values: youtubeScopes.map(text) },
        { text: t('「建立用戶端」選「網頁應用程式」，在「已授權的重新導向 URI」貼上這串網址，按「建立」。'), links: [link(t('建立用戶端'), 'https://console.cloud.google.com/auth/clients/create')], values: [callback('youtube')] },
        { text: t('建立後立刻把畫面上的「用戶端 ID」和「用戶端密鑰」貼到工作檯 YouTube 卡片；密鑰只會顯示這一次，可以先按「下載 JSON」備存。'), check: t('工作檯兩個欄位都改顯示遮蔽過的內容。') },
        { text: t('回到工作檯按「連結 YouTube 帳號」，選擁有頻道的帳號、權限全部勾選。看到「已連結」就完成，資料約每小時同步一次。'), check: t('YouTube 卡片顯示頻道名稱與「已連結」。') },
      ],
    }],
  },
  notify: {
    id: 'notify',
    title: t('LINE 通知設定教學'),
    minutes: 20,
    needs: [t('一個 LINE 帳號'), t('一個要收通知的 LINE 群組'), t('工作檯已設定公開的 Webhook 網址（下方顯示「尚未設定」時請管理員先設定）')],
    faq: [
      t('群組選單是空的：先把官方帳號加進群組，再傳一則訊息；順序反了工作檯收不到群組。'),
      t('官方帳號 User ID 不用自己找：按「測試連線」成功後會自動填入。'),
      t('按「Verify」失敗：確認 Webhook 網址是用複製鈕整串貼上。'),
    ],
    sections: [{
      steps: [
        { text: t('在 LINE 官方帳號管理後台建立一個官方帳號（這就是發通知的機器人）。'), links: [link(t('開啟 LINE 官方帳號管理後台'), 'https://manager.line.biz/')] },
        { text: t('管理後台「設定 → Messaging API」按「啟用 Messaging API」；再到「設定 → 帳號設定」的「功能切換」，把「加入群組或多人聊天室」改成「接受邀請加入群組或多人聊天室」。') },
        { text: t('在 LINE Developers 的同名 channel 複製 Channel secret（Basic settings）和 Channel access token（Messaging API 最下方按「Issue」），貼到工作檯。'), links: [link(t('開啟 LINE Developers'), 'https://developers.line.biz/console/')] },
        { text: t('「Messaging API → Webhook settings」在「Webhook URL」按「Edit」貼上這串網址，按「Update」→「Verify」，再打開「Use webhook」。'), values: [{ kind: 'webhook', path: '/webhook/line-notify' }], check: t('按「Verify」後看到「Success」。') },
        { text: t('把官方帳號邀進群組，在群組傳一則訊息；到工作檯「設定 → LINE 群組通知」選這個群組，「品牌通知」改「啟用」並儲存。') },
        { text: t('回到工作檯「平台連線」，在 LINE 通知卡片按「測試連線」，看到「連線成功」就完成（官方帳號 User ID 會自動填入）。'), check: t('畫面顯示「連線成功」。') },
      ],
    }],
  },
  jev: {
    id: 'jev',
    title: t('jev 設定教學'),
    minutes: 5,
    needs: [t('一個 TypeSafe 帳號（jev 是 TypeSafe 的判斷模型，工作檯用它替留言做快速分類與判斷）')],
    faq: [
      t('「API 網址」不用填：留空就會用官方網址；只接受 https://api.typesafe.ai/v1。'),
      t('測試連線失敗：確認金鑰整串複製、沒有多空白，且 TypeSafe 帳號仍可使用。'),
    ],
    sections: [{
      steps: [
        { text: t('登入 TypeSafe 主控台，在「API Keys」建立一組金鑰並複製（像密碼，不要給別人）。'), links: [link(t('開啟 TypeSafe 金鑰頁'), 'https://console.typesafe.ai/keys')] },
        { text: t('回到工作檯 jev 卡片，「API 金鑰」按「設定」，貼上並按「儲存」；「API 網址」留空即可。'), check: t('「API 金鑰」改顯示遮蔽過的內容。') },
        { text: t('回到工作檯「平台連線」，在 jev 卡片按「測試連線」，看到「連線成功」就完成。'), check: t('畫面顯示「連線成功」。') },
      ],
    }],
  },
  webhook: {
    id: 'webhook',
    title: t('Webhook 設定教學'),
    minutes: 15,
    needs: [t('一個 ngrok 帳號（免費即可）'), t('能修改工作檯主機上的 .env 並重新啟動工作檯（通常是管理員）'), t('已完成 Facebook 粉專與 Instagram 設定')],
    faq: [
      t('Webhook 是平台主動通知工作檯「有新留言」的網址；沒設定時工作檯仍會每小時自己去抓，只是比較慢。'),
      t('Meta 的應用程式在開發模式時，Webhook 只會送出後台的測試事件，以及有應用程式角色的人（管理員、開發人員、測試人員）自己留言的事件；其他人的留言要等應用程式上線才會即時收到。Instagram 留言一律要上線，並且需要進階存取權限。'),
      t('「WEBHOOK_PUBLIC_URL」一直是「尚未設定」：確認 NGROK_AUTHTOKEN 已填並重新啟動工作檯。'),
      t('按「驗證並儲存」失敗：回呼網址要整串複製，驗證權杖要和工作檯 Meta 卡片的「Webhook 驗證權杖」完全相同。'),
    ],
    sections: [
      {
        heading: t('公開網址（ngrok）'),
        steps: [
          { text: t('登入 ngrok，在「Your Authtoken」頁複製 Authtoken。'), links: [link(t('開啟 ngrok Authtoken'), 'https://dashboard.ngrok.com/get-started/your-authtoken')] },
          { text: t('在工作檯主機的 .env 找到 NGROK_AUTHTOKEN 這一行，把 Authtoken 貼在等號後面，然後重新啟動工作檯（執行 scripts/start-all.ps1）。這個值只能放 .env，不能在網頁設定。') },
          { text: t('回到工作檯「平台連線」，Webhook 卡片的「WEBHOOK_PUBLIC_URL」出現 https:// 開頭的網址就完成；這是 ngrok 指派給你的固定網址。'), check: t('WEBHOOK_PUBLIC_URL 不再顯示「尚未設定」。') },
        ],
      },
      {
        heading: t('Meta 即時留言通知'),
        steps: [
          { text: t('在工作檯 Meta 卡片展開「手動設定（進階）」，「Webhook 驗證權杖」按「設定」，自己取一串英數字（像密碼）並儲存，同時記下來。') },
          { text: t('開 Meta 開發者後台，打開你的應用程式，左側「Webhooks」選「Page」，按「訂閱這個物件」，回呼網址貼上這串網址，驗證權杖填剛才那串，按「驗證並儲存」。'), links: [link(t('開啟 Meta 開發者後台'), 'https://developers.facebook.com/apps/')], values: [{ kind: 'webhook', path: '/webhook/meta-inbound' }] },
          { text: t('在 Page 的欄位清單找到「feed」按「訂閱」；有 Instagram 時在上方下拉選單改選「Instagram」物件，同樣填網址與權杖，訂閱「comments」。'), check: t('欄位旁顯示已訂閱。') },
          { text: t('回到工作檯「平台連線」，在 Meta 卡片按「測試連線」，看到「權限檢查完成」就完成；之後有新留言會即時進來。'), check: t('畫面顯示「權限檢查完成」。') },
        ],
      },
    ],
  },
  tiktok: {
    id: 'tiktok',
    title: t('TikTok 設定教學'),
    minutes: 20,
    needs: [
      t('之後要連結的 TikTok 帳號'),
      t('公開的服務條款與隱私權政策網址（TikTok 的 Sandbox 也必填）'),
      t('{instruction}（回呼網址才會顯示）', { instruction: internalHttps }),
    ],
    faq: [
      t('不用送審：只用 Sandbox，送到收件匣的影片由你在 App 裡完成發佈；未審核時直接用 API 發佈只能僅自己可見，而且發文帳號必須設為私人帳號。'),
      t('「Apply changes」出現紅字：App icon、Category、Description、服務條款與隱私權政策網址都要填，App name 不能含「TikTok」。'),
      t('回呼網址顯示「尚未設定」：{instruction}後再打開這份教學。', { instruction: internalHttps }),
      t('僅支援影片發布，圖文需從APP上傳。'),
      t('「Verify domains」不用按：工作檯從本機直接上傳影片，不需要驗證網域。'),
    ],
    sections: [
      {
        heading: t('建立應用程式（Sandbox）'),
        steps: [
          { text: t('登入 TikTok for Developers，從右上「Developer Portal」建立應用程式；名稱不能含「TikTok」，例如用你的品牌名。'), links: [link(t('開啟 TikTok for Developers'), 'https://developers.tiktok.com/')] },
          { text: t('頁面上方切到「Sandbox」建立一個；「Add products」加入 Login Kit 與 Content Posting API（Direct Post 保持關閉）。') },
          { text: t('Login Kit 的「Redirect URI」選 Web 貼上回呼網址；「Scopes」用「Add scopes」加入其餘權限。'), values: [callback('tiktok'), ...tiktokScopes.map(text)] },
          { text: t('「Target Users」按「Add account」，登入你的 TikTok 帳號並同意開發者條款；Basic information 的必填欄位填好後按「Apply changes」。'), check: t('套用後沒有紅字；重新整理後 Target Users 列出你的帳號（可能要等最多 1 小時）。') },
        ],
      },
      {
        heading: t('連結帳號'),
        steps: [
          { text: t('把 Sandbox 頁「Credentials」的 Client key 與 Client secret 分別貼到工作檯 TikTok 卡片並儲存（像帳號密碼，不要給別人）。'), check: t('兩個欄位改顯示遮蔽過的內容。') },
          { text: t('回到工作檯「平台連線」，在 TikTok 卡片按「連結 TikTok 帳號」，登入並同意授權，看到「已連結」就完成。'), check: t('卡片顯示「已連結」與一年後的到期日。') },
        ],
      },
      {
        heading: t('讀取留言（需要公司身分）'),
        steps: [
          { text: t('{notice}。申請要登記文件上的公司全名、公司網域信箱與公司網站，個人可略過。', { notice: tiktokCommentNotice }) },
        ],
      },
    ],
  },
};

// 把教學中的網址描述換成實際字串；缺少設定時回傳空字串，由畫面顯示「尚未設定」。
export function resolveGuideValue(value: GuideValue, context: GuideContext): string {
  if (value.kind === 'text') return value.value;
  if (value.kind === 'callback') return context.callbacks?.[value.platform] || '';
  return context.webhookUrl ? context.webhookUrl.replace(/\/$/, '') + value.path : '';
}
