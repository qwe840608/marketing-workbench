import test from 'node:test';
import assert from 'node:assert/strict';
import vectors from '../../shared/publish_threads_vectors.json' with { type: 'json' };
import { overflowAt, overLimitReason, textLength, textBytes, youtubeTitle, defaultPlatformOptions, loadedPlatformOptions, checkComposer, IG_COVER_PNG_WARNING, IG_COVER_RATIO_WARNING, FB_COVER_RATIO_WARNING, foldCaption, previewRatio, hashtags, mentions } from '../src/publishComposer.ts';

for (const c of vectors.cases) test('共用 Threads 向量：' + c.name, () => {
  assert.equal(textLength(c.text), c.length);
});
const rules = { facebook: { caption: 63206, carousel: 10, video_seconds: 14400, reels_seconds_min: 3, reels_seconds_max: 90 }, instagram: { caption: 2200, hashtag: 30, mentions: 20, carousel: 10, video_seconds: 900 }, threads: { caption: 500, hashtag: 1, carousel: 20, video_seconds: 300 } };
const video = { mime: 'video/mp4', width: 1080, height: 1920, duration: 12 };
test('文案折疊門檻、行數、展開與 Unicode 不截斷代理對', () => {
  assert.deepEqual(foldCaption('文'.repeat(125), 'instagram'), { text: '文'.repeat(125), folded: false });
  assert.equal(foldCaption('文'.repeat(126), 'instagram').text, '文'.repeat(125) + '…');
  assert.equal(foldCaption('😀'.repeat(126), 'instagram').text, '😀'.repeat(125) + '…');
  assert.equal(foldCaption('一\n二\n三', 'instagram').text, '一\n二…');
  assert.equal(foldCaption('文'.repeat(500), 'facebook', true).text.length, 500);
  assert.equal(foldCaption('文'.repeat(280), 'threads').folded, false);
  assert.equal(foldCaption('一\n二\n三\n四\n' + '文'.repeat(490), 'threads').folded, false);
});
test('預設 Reels／同時顯示動態與舊草稿 feed', () => {
  assert.equal(defaultPlatformOptions().facebook.video_format, 'reels');
  assert.equal(defaultPlatformOptions().instagram.share_to_feed, true);
  assert.equal(loadedPlatformOptions().facebook.video_format, 'feed');
});
test('IG 文案、hashtag、@ 上限與單字邊界', () => {
  const o = defaultPlatformOptions();
  const valid = checkComposer('instagram', 'video', '文'.repeat(2200), [video], o, rules);
  assert.deepEqual(valid.errors, []);
  const r = checkComposer('instagram', 'video', '文'.repeat(2201) + ' ' + '#標籤 '.repeat(31) + '@帳號 '.repeat(21), [video], o, rules);
  assert(r.errors.some(e => e.includes('hashtag 超過 1')));
  assert(r.errors.some(e => e.includes('@ 超過 1')));
  assert(r.errors.some(e => e.includes('文案超過')));
  assert.deepEqual(hashtags('文#不是 #主題 #第二'), ['#主題', '#第二']);
  // 標點後的文字不屬於 hashtag（在 Threads 第一段 hashtag 後面直接補字的情境）。
  assert.deepEqual(hashtags('第一行 #主題，在第一段補字。#第二! #third_tag.'), ['#主題', '#第二', '#third_tag']);
  assert.deepEqual(mentions('mail@none @帳號'), ['@帳號']);
});
test('FB Reels 秒數與比例（FB 草稿也套用 Reels 規則）、@ 提示', () => {
  const o = defaultPlatformOptions();
  for (const duration of [3, 90]) assert.deepEqual(checkComposer('facebook', 'video', '', [{ ...video, duration }], o, rules).errors, []);
  assert(checkComposer('facebook', 'video', '@帳號', [{ ...video, duration: 91, width: 1920, height: 1080 }], o, rules).errors.length === 2);
  const r = checkComposer('facebook', 'video', '@帳號', [{ ...video, duration: 91 }], o, rules, true);
  assert.deepEqual(r.errors, ['影片長度需 3–90 秒']);
  assert.equal(r.warnings.length, 1);
  assert.equal(checkComposer('facebook', 'video', '單獨 @', [video], o, rules).warnings.length, 1);
});
test('Threads 手動超限、空段、主題標籤與素材數', () => {
  const o = defaultPlatformOptions();
  o.threads = { segments: ['文'.repeat(501), ''], segments_custom: true };
  assert.equal(checkComposer('threads', 'text', '', [], o, rules).errors.length, 2);
  o.threads.segments = ['#主題 #第二'];
  const r = checkComposer('threads', 'text', '', [], o, rules);
  assert.equal(r.topicTag, '主題'); assert.equal(r.warnings.length, 1);
  assert(checkComposer('threads', 'carousel', '', [video], o, rules).errors.length);
});
test('素材預覽比例', () => {
  const o = defaultPlatformOptions();
  assert.equal(previewRatio('instagram', 'video', video, o, false), '9 / 16');
  assert.equal(previewRatio('facebook', 'video', video, o, true), '9 / 16');
  assert.equal(previewRatio('facebook', 'video', video, { ...o, facebook: { video_format: 'feed' } }, true), '1080 / 1920');
  assert.equal(previewRatio('instagram', 'image', { ...video, width: 1000, height: 1000 }, o, false), '1 / 1');
  assert.equal(previewRatio('instagram', 'image', video, o, false), '4 / 5');
});


test('限動不帶文字、平台／10則／3–60秒／JPEG與比例提示', () => {
  const o = defaultPlatformOptions(), jpeg = { mime: 'image/jpeg', width: 1080, height: 1920, duration: null, size: 8 * 1024 ** 2 };
  for (const duration of [3, 60]) assert.deepEqual(checkComposer('instagram', 'story', '', [{ ...video, duration }], o, rules).errors, []);
  for (const duration of [2.9, 60.1]) assert(checkComposer('instagram', 'story', '', [{ ...video, duration }], o, rules).errors.length);
  assert(checkComposer('facebook', 'story', '', [{ ...video, duration: 61 }], o, rules).errors.length);
  assert.deepEqual(checkComposer('instagram', 'story', '', Array(10).fill(jpeg), o, rules).errors, []);
  assert(checkComposer('instagram', 'story', '', Array(11).fill(jpeg), o, rules).errors.length);
  assert(checkComposer('instagram', 'story', '文字', [jpeg], o, rules).errors.length);
  assert(checkComposer('threads', 'story', '', [jpeg], o, rules).errors.length);
  // IG 的 PNG 由後端自動轉 JPEG：不再是錯誤，改為警告；其他格式仍是錯誤，FB 不受影響。
  const png = checkComposer('instagram', 'story', '', [{ ...jpeg, mime: 'image/png' }], o, rules);
  assert.deepEqual(png.errors, []); assert(png.warnings.some(w => w.includes('自動把 PNG 轉成 JPEG')));
  assert(checkComposer('instagram', 'story', '', [{ ...jpeg, mime: 'image/gif' }], o, rules).errors.length);
  assert.deepEqual(checkComposer('facebook', 'story', '', [{ ...jpeg, mime: 'image/png' }], o, rules).warnings, []);
  assert(checkComposer('instagram', 'story', '', [{ ...jpeg, mime: 'image/png', size: jpeg.size + 1 }], o, rules).errors.length);
  assert(checkComposer('instagram', 'story', '', [{ ...jpeg, size: jpeg.size + 1 }], o, rules).errors.length);
  const landscape = { ...jpeg, width: 1920, height: 1080 };
  const check = checkComposer('instagram', 'story', '', [landscape], o, rules);
  assert.deepEqual(check.errors, []); assert(check.warnings[0].includes('平台會加邊'));
  assert.equal(previewRatio('facebook', 'story', landscape, o, false), '9 / 16');
});


const youtubeRule = { title: 100, caption: 5000, video_seconds: 43200, hashtag_effective: 15, long_video_seconds: 900, shorts_seconds: 180, shorts_thumbnail: false, thumbnail_bytes: 2 * 1024 ** 2, thumbnail_min_width: 640, thumbnail_mimes: ['image/jpeg', 'image/png'] };
const youtubeRules = { ...rules, youtube: youtubeRule };
const landscape = { mime: 'video/mp4', width: 1920, height: 1080, duration: 12, size: 1000 };
const thumbnail = { mime: 'image/jpeg', width: 1280, height: 720, duration: null, size: 1000 };
const withYoutube = patch => ({ ...defaultPlatformOptions(), youtube: { ...defaultPlatformOptions().youtube, ...patch } });
test('YouTube 標題空白沿用說明第一個非空行，位元組與字元分開計算', () => {
  assert.equal(youtubeTitle('', '\n  第一行  \n第二行'), '第一行');
  assert.equal(youtubeTitle('  自訂  ', '第一行'), '自訂');
  assert.equal(youtubeTitle('', ' \n '), '');
  assert.equal(textBytes('字'.repeat(1667)), 5001);
  assert.equal(textBytes('a'.repeat(5000)), 5000);
});
test('YouTube 只支援影片，其他格式只回「YouTube 只支援影片」', () => {
  for (const format of ['image', 'carousel', 'text']) assert.deepEqual(checkComposer('youtube', format, '標題', [], withYoutube({}), youtubeRules).errors, ['YouTube 只支援影片']);
  assert.deepEqual(checkComposer('youtube', 'video', '標題\n說明', [landscape], withYoutube({}), youtubeRules).errors, []);
});
test('YouTube 標題 100 字與說明 5000 位元組邊界', () => {
  const ok = checkComposer('youtube', 'video', 'a'.repeat(5000), [landscape], withYoutube({ title: '字'.repeat(100) }), youtubeRules);
  assert.deepEqual(ok.errors, []);
  assert(checkComposer('youtube', 'video', '說明', [landscape], withYoutube({ title: '字'.repeat(101) }), youtubeRules).errors.some(e => e.includes('標題最多 100 字')));
  assert(checkComposer('youtube', 'video', '字'.repeat(1667), [landscape], withYoutube({ title: '標題' }), youtubeRules).errors.some(e => e.includes('5,000 位元組')));
  assert.deepEqual(checkComposer('youtube', 'video', '字'.repeat(1666) + 'ab', [landscape], withYoutube({ title: '標題' }), youtubeRules).errors, []);
  assert(checkComposer('youtube', 'video', '', [landscape], withYoutube({}), youtubeRules).errors.includes('標題必填'));
});
test('YouTube Shorts 提示與縮圖：Shorts 不支援，非 16:9 只提示', () => {
  const short = { ...landscape, width: 1080, height: 1920 };
  assert(checkComposer('youtube', 'video', '標題', [short], withYoutube({}), youtubeRules).warnings.some(w => w.includes('Shorts')));
  assert(!checkComposer('youtube', 'video', '標題', [{ ...short, duration: 181 }], withYoutube({}), youtubeRules).warnings.some(w => w.includes('Shorts')));
  assert(checkComposer('youtube', 'video', '標題', [short], withYoutube({}), youtubeRules, false, thumbnail).errors.some(e => e.includes('Shorts 不支援自訂縮圖')));
  const square = checkComposer('youtube', 'video', '標題', [landscape], withYoutube({}), youtubeRules, false, { ...thumbnail, width: 1000, height: 1000 });
  assert.deepEqual(square.errors, []); assert(square.warnings.some(w => w.includes('16:9')));
  assert(checkComposer('youtube', 'video', '標題', [landscape], withYoutube({}), youtubeRules, false, { ...thumbnail, size: 2 * 1024 ** 2 + 1 }).errors.some(e => e.includes('2 MB')));
  assert.deepEqual(checkComposer('youtube', 'video', '標題', [landscape], withYoutube({}), youtubeRules, false, { ...thumbnail, size: 2 * 1024 ** 2 }).errors, []);
  assert(checkComposer('youtube', 'video', '標題', [landscape], withYoutube({}), youtubeRules, false, { ...thumbnail, mime: 'image/gif' }).errors.some(e => e.includes('JPG／PNG')));
});
test('YouTube 超過 15 分鐘與 15 個 hashtag 只提示', () => {
  const long = checkComposer('youtube', 'video', '標題 ' + '#標籤 '.repeat(16), [{ ...landscape, duration: 901 }], withYoutube({}), youtubeRules);
  assert.deepEqual(long.errors, []); assert.equal(long.warnings.length, 2);
});
test('YouTube 預覽比例與縮圖不進表單選項', () => {
  assert.equal(previewRatio('youtube', 'video', landscape, withYoutube({}), false), '16 / 9');
  assert.equal(previewRatio('youtube', 'video', { ...landscape, width: 1080, height: 1920 }, withYoutube({}), false), '9 / 16');
  const loaded = loadedPlatformOptions({ ...defaultPlatformOptions(), youtube: { title: 'T', privacy: 'private', made_for_kids: true, thumbnail_media_id: 7 } });
  assert.deepEqual(loaded.youtube, { title: 'T', privacy: 'private', made_for_kids: true });
  assert.deepEqual(loadedPlatformOptions().youtube, { title: '', privacy: 'public', made_for_kids: false });
  assert.equal(foldCaption('一\n二\n三\n四', 'youtube').folded, true);
});
test('Instagram Reels 封面：只收 JPG／PNG、8 MB 內，非 9:16 與 PNG 只提示，封面編號不進表單', () => {
  const igRules = { ...rules, instagram: { ...rules.instagram, cover_bytes: 8 * 1024 ** 2, cover_mimes: ['image/jpeg', 'image/png'] } };
  const reel = { mime: 'video/mp4', width: 1080, height: 1920, duration: 12, size: 1000 };
  const cover = { mime: 'image/jpeg', width: 1080, height: 1920, duration: null, size: 1000 };
  const o = defaultPlatformOptions();
  const plain = checkComposer('instagram', 'video', '文案', [reel], o, igRules, false, null, cover);
  assert.deepEqual([plain.errors, plain.warnings], [[], []]);
  assert.deepEqual(checkComposer('instagram', 'video', '文案', [reel], o, igRules, false, null, { ...cover, width: 1080, height: 1080 }).warnings, [IG_COVER_RATIO_WARNING]);
  assert.deepEqual(checkComposer('instagram', 'video', '文案', [reel], o, igRules, false, null, { ...cover, mime: 'image/png' }).warnings, [IG_COVER_PNG_WARNING]);
  assert(checkComposer('instagram', 'video', '文案', [reel], o, igRules, false, null, { ...cover, size: 8 * 1024 ** 2 + 1 }).errors.some(e => e.includes('8 MB')));
  assert(checkComposer('instagram', 'video', '文案', [reel], o, igRules, false, null, { ...cover, mime: 'image/gif' }).errors.includes('封面只支援 JPG／PNG'));
  assert.deepEqual(loadedPlatformOptions({ ...o, instagram: { share_to_feed: false, cover_media_id: 3 } }).instagram, { share_to_feed: false });
});
test('Facebook 影片封面：只收 JPG／PNG、8 MB 內，比例與影片不同只提示，封面編號不進表單', () => {
  const fbRules = { ...rules, facebook: { ...rules.facebook, cover_bytes: 8 * 1024 ** 2, cover_mimes: ['image/jpeg', 'image/png'] } };
  const reel = { mime: 'video/mp4', width: 1080, height: 1920, duration: 12, size: 1000 };
  const cover = { mime: 'image/jpeg', width: 1080, height: 1920, duration: null, size: 1000 };
  const o = defaultPlatformOptions();
  const plain = checkComposer('facebook', 'video', '文案', [reel], o, fbRules, false, null, cover);
  assert.deepEqual([plain.errors, plain.warnings], [[], []]);
  assert.deepEqual(checkComposer('facebook', 'video', '文案', [reel], o, fbRules, false, null, { ...cover, height: 1080 }).warnings, [FB_COVER_RATIO_WARNING]);
  assert(checkComposer('facebook', 'video', '文案', [reel], o, fbRules, false, null, { ...cover, size: 8 * 1024 ** 2 + 1 }).errors.some(e => e.includes('8 MB')));
  assert(checkComposer('facebook', 'video', '文案', [reel], o, fbRules, false, null, { ...cover, mime: 'image/gif' }).errors.includes('封面只支援 JPG／PNG'));
  assert.deepEqual(loadedPlatformOptions({ ...o, facebook: { video_format: 'reels', cover_media_id: 4 } }).facebook, { video_format: 'reels' });
});

test('超過 Threads 上限時指出從第幾個字開始超出（與後端相同文字），不自動拆段', () => {
  assert.equal(overflowAt('甲'.repeat(500), 500), null);
  assert.deepEqual(overflowAt('甲'.repeat(500) + '乙丙', 500), { position: 501, snippet: '乙丙' });
  assert.deepEqual(overflowAt('😀'.repeat(126), 500), { position: 126, snippet: '😀' });
  assert.deepEqual(overflowAt('甲'.repeat(499) + '😀尾', 500), { position: 500, snippet: '😀尾' });
  assert.equal(overLimitReason('Threads 文案', '甲'.repeat(500) + '乙丙丁', 500), 'Threads 文案超過 500 字上限：共 503 字，從第 501 個字「乙丙丁」開始超出');
  const result = checkComposer('threads', 'text', '', [], { ...defaultPlatformOptions(), threads: { segments: ['短', '丙'.repeat(501)], segments_custom: true } }, rules);
  assert.ok(result.errors.includes('回覆 1超過 500 字上限：共 501 字，從第 501 個字「丙」開始超出'), result.errors.join());
});

test('Instagram 一般貼文 PNG 為警告（輪播只列一次），其他格式為錯誤', () => {
  const o = defaultPlatformOptions(), image = { mime: 'image/png', width: 1080, height: 1080, duration: null, size: 1000 };
  const single = checkComposer('instagram', 'image', '', [image], o, rules);
  assert.deepEqual(single.errors, []); assert.deepEqual(single.warnings, ['Instagram 會自動把 PNG 轉成 JPEG，透明背景會變白底']);
  assert.deepEqual(checkComposer('instagram', 'carousel', '', [image, image], o, rules).warnings.length, 1);
  assert(checkComposer('instagram', 'image', '', [{ ...image, mime: 'image/gif' }], o, rules).errors.some(e => e.includes('JPEG 或 PNG')));
  for (const platform of ['facebook', 'threads']) assert.deepEqual(checkComposer(platform, 'image', '', [image], o, rules).warnings, []);
});
