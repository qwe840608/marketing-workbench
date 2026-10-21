import test from 'node:test';
import assert from 'node:assert/strict';
import { platformGuides, resolveGuideValue, facebookPermissions, instagramPermissions, threadsPermissions, youtubeScopes, tiktokScopes, tiktokCommentNotice, guideLinkHosts } from '../src/platformGuides.ts';

const stepsOf = guide => guide.sections.flatMap(section => section.steps);

test('IG／FB、Threads、YouTube、LINE、jev、Webhook、TikTok 都有教學、預估時間、開始前需要與常見問題，且沒有空步驟', () => {
  assert.deepEqual(Object.keys(platformGuides).sort(), ['jev', 'meta', 'notify', 'threads', 'tiktok', 'webhook', 'youtube']);
  for (const [id, guide] of Object.entries(platformGuides)) {
    assert.equal(guide.id, id);
    assert.ok(guide.title.trim(), id);
    assert.ok(guide.sections.length, id);
    assert.ok(Number.isInteger(guide.minutes) && guide.minutes > 0, id + ' 預估時間');
    assert.ok(guide.needs.length && guide.needs.every(need => need.trim()), id + ' 開始前你需要');
    assert.ok(guide.faq.length && guide.faq.every(item => item.trim()), id + ' 常見問題');
    // 精簡版：每份教學最多 7 步、每步一兩句話。
    assert.ok(stepsOf(guide).length <= 7, id + ' 步驟數');
    for (const step of stepsOf(guide)) assert.ok(step.text.length <= 120, id + ' 步驟過長：' + step.text);
    for (const section of guide.sections) {
      assert.ok(section.steps.length, id);
      for (const step of section.steps) {
        assert.ok(step.text.trim().length > 4, id + ' 步驟文字');
        for (const value of step.values || []) assert.ok(value.kind !== 'text' || value.value.trim(), id + ' 空白可複製值');
      }
    }
  }
});

test('Meta 教學分 Facebook、Instagram、連結帳號三節並列出 operations.md 的完整權限', () => {
  const meta = platformGuides.meta;
  assert.equal(meta.sections.length, 3);
  assert.ok(meta.sections[0].heading.startsWith('Facebook'));
  assert.ok(meta.sections[1].heading.startsWith('Instagram'));
  assert.equal(meta.sections[2].heading, '連結帳號');
  const copied = meta.sections.flatMap(s => s.steps.flatMap(step => step.values || [])).filter(v => v.kind === 'text').map(v => v.value).join(', ');
  for (const scope of [...facebookPermissions, ...instagramPermissions]) assert.ok(copied.includes(scope), scope);
  assert.equal(facebookPermissions.length + instagramPermissions.length, 10);
  assert.deepEqual(threadsPermissions, ['threads_basic', 'threads_content_publish', 'threads_manage_replies', 'threads_manage_insights', 'threads_read_replies']);
});

test('Meta、Threads、YouTube 教學都帶入各自的回呼網址，LINE 帶入 Webhook 網址', () => {
  const context = { callbacks: { meta: 'https://office.example.test/api/oauth/meta/callback', threads: 'https://office.example.test/api/oauth/threads/callback', youtube: 'https://office.example.test/api/oauth/youtube/callback' }, webhookUrl: 'https://hook.example.test/' };
  for (const platform of ['meta', 'threads', 'youtube']) {
    const values = stepsOf(platformGuides[platform]).flatMap(step => step.values || []);
    const callbackValues = values.filter(v => v.kind === 'callback').map(v => resolveGuideValue(v, context));
    assert.deepEqual(callbackValues, [context.callbacks[platform]], platform);
  }
  const webhook = stepsOf(platformGuides.notify).flatMap(step => step.values || []).filter(v => v.kind === 'webhook');
  assert.deepEqual(webhook.map(v => resolveGuideValue(v, context)), ['https://hook.example.test/webhook/line-notify']);
  // 尚未設定時回傳空字串，畫面顯示「尚未設定」且複製停用。
  assert.equal(resolveGuideValue({ kind: 'callback', platform: 'youtube' }, {}), '');
  assert.equal(resolveGuideValue(webhook[0], {}), '');
});

test('YouTube 教學涵蓋兩個 API、三個範圍、品牌帳戶與 Google 主控台用語；TikTok 依實際後台用語帶到連結帳號', () => {
  const youtube = stepsOf(platformGuides.youtube).map(s => s.text + (s.values || []).map(v => v.value || '').join('')).join('\n') + platformGuides.youtube.faq.join('');
  for (const word of ['YouTube Data API v3', 'YouTube Analytics API', 'youtube.readonly', 'yt-analytics.readonly', 'youtube.upload', '品牌帳戶', '進階', '（不安全）', '新增或移除範圍', '手動新增範圍', '新增至資料表', '更新', '儲存', '實際運作中']) assert.ok(youtube.includes(word), word);
  const copied = stepsOf(platformGuides.youtube).flatMap(step => step.values || []).filter(v => v.kind === 'text').map(v => v.value);
  assert.deepEqual(copied, youtubeScopes);
  assert.equal(youtubeScopes.length, 3);
  const tiktok = platformGuides.tiktok.needs.join('') + platformGuides.tiktok.faq.join('') + stepsOf(platformGuides.tiktok).map(s => s.text).join('\n');
  // 2026-10-16 實機核對的後台用語；Display API 已不是獨立產品，權限直接在 Scopes 加。
  for (const word of ['TikTok for Developers', 'Developer Portal', 'Login Kit', 'Content Posting API', 'Direct Post', 'Redirect URI', 'Add scopes', 'Sandbox', 'Target Users', 'Add account', 'Apply changes', 'Client key', 'Client secret', '連結 TikTok 帳號', '「已連結」', '審核', '僅自己可見', '僅支援影片發布，圖文需從APP上傳', 'Verify domains']) assert.ok(tiktok.includes(word), word);
  for (const word of ['Display API', 'Manage apps', '尚未支援']) assert.ok(!tiktok.includes(word), word);
});

test('TikTok 教學：Web 回呼網址、第一版四個權限，並說明讀留言需要公司身分', () => {
  const values = stepsOf(platformGuides.tiktok).flatMap(step => step.values || []);
  const callback = values.filter(v => v.kind === 'callback');
  assert.deepEqual(callback.map(v => v.platform), ['tiktok']);
  const callbacks = { tiktok: 'https://office.example.test/api/oauth/tiktok/callback' };
  assert.equal(resolveGuideValue(callback[0], { callbacks }), callbacks.tiktok);
  assert.deepEqual(values.filter(v => v.kind === 'text').map(v => v.value), tiktokScopes);
  assert.deepEqual(tiktokScopes, ['user.info.basic', 'user.info.stats', 'video.list', 'video.upload']);
  // 第一版不送審、不直接發佈，所以不能要求 video.publish。
  assert.ok(!JSON.stringify(platformGuides.tiktok).includes('video.publish'));
  const comments = platformGuides.tiktok.sections.find(section => section.heading === '讀取留言（需要公司身分）');
  assert.ok(comments && comments.steps[0].text.startsWith(tiktokCommentNotice), '留言提示');
  assert.equal(tiktokCommentNotice, '讀取 TikTok 留言需要以公司身分申請 TikTok API for Business（個人開發者無法申請）');
});

test('每份教學都有確認點；除 TikTok 外最後一步回到工作檯，並說明已連結與每小時同步', () => {
  for (const [id, guide] of Object.entries(platformGuides)) {
    const steps = stepsOf(guide);
    assert.ok(steps.some(step => step.check && step.check.trim()), id + ' 確認點');
    if (id === 'tiktok') continue;
    const last = steps[steps.length - 1].text;
    assert.ok(last.startsWith('回到工作檯'), id + ' 最後一步回到工作檯');
    if (id === 'notify' || id === 'jev') assert.ok(last.includes('測試連線') && last.includes('連線成功'), id);
    else if (id === 'webhook') assert.ok(last.includes('測試連線') && last.includes('權限檢查完成'), id);
    else {
      const button = { meta: '連結 Meta 帳號', threads: '連結 Threads 帳號', youtube: '連結 YouTube 帳號' }[id];
      assert.ok(last.includes('「' + button + '」') && last.includes('「已連結」') && last.includes('每小時'), id + ' 已連結／每小時');
    }
  }
  // 各平台最容易卡關的地方都要有對應說明。
  assert.ok(JSON.stringify(platformGuides.notify).includes('先把官方帳號加進群組，再傳一則訊息'));
  assert.ok(JSON.stringify(platformGuides.youtube).includes('尚未驗證') && JSON.stringify(platformGuides.youtube).includes('每 7 天'));
  assert.ok(JSON.stringify(platformGuides.meta).includes('編輯設定'));
});

test('要去其他平台的步驟都附 https 直達連結，網域限定在各平台後台，且不含外部圖片', () => {
  const all = JSON.stringify(platformGuides);
  assert.ok(!/<a\b|target=|<img|\.(png|jpe?g|gif|svg)\b/i.test(all));
  for (const [id, guide] of Object.entries(platformGuides)) {
    const links = stepsOf(guide).flatMap(step => step.links || []);
    assert.ok(links.length, id + ' 至少一個連結');
    assert.ok(stepsOf(guide)[0].links?.length, id + ' 第一步就有連結');
    for (const item of links) {
      const url = new URL(item.url);
      assert.equal(url.protocol, 'https:', item.url);
      assert.ok(guideLinkHosts.includes(url.hostname), item.url);
      assert.ok(item.label.trim(), item.url);
    }
  }
  for (const word of ['projectcreate', 'youtube.googleapis.com', 'youtubeanalytics.googleapis.com', 'auth/scopes', 'auth/clients/create']) assert.ok(JSON.stringify(platformGuides.youtube).includes(word), word);
});

test('教學內容不含真實帳號、本機路徑或金鑰字樣', () => {
  const all = JSON.stringify(platformGuides);
  assert.ok(!/[A-Za-z]:\\|@gmail|Bearer |secret=|token=/i.test(all));
});

test('權限一個一列各自可複製（Meta 沒有一次全部新增），LINE User ID 改為測試連線自動填入', () => {
  const copied = guide => stepsOf(guide).flatMap(step => step.values || []).filter(v => v.kind === 'text').map(v => v.value);
  assert.deepEqual(copied(platformGuides.meta), [...facebookPermissions, ...instagramPermissions]);
  assert.deepEqual(copied(platformGuides.threads), threadsPermissions);
  assert.ok(threadsPermissions.includes('threads_manage_replies'));
  assert.ok(!JSON.stringify(platformGuides.notify).includes('Get bot info'));
  assert.ok(JSON.stringify(platformGuides.notify).includes('自動填入'));
  assert.deepEqual(stepsOf(platformGuides.webhook).flatMap(step => step.values || []).map(v => v.kind === 'webhook' && v.path), ['/webhook/meta-inbound']);
});
