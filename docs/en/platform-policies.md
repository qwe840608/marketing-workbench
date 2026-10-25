# Platform policies and API limits

> **Language / 語言 / 语言 / 言語**: [繁體中文](../zh-tw/平台政策.md) | [简体中文](../cn/平台政策与API限制.md) | English | [日本語](../jp/プラットフォームポリシー.md)

This document collects the platform terms and API specifications the workbench runs into, so they don't have to be looked up again every time. Each item notes its source and verification date; **"Inference"** marks our own judgment based on the text, and **"Unverified"** marks claims we have not yet found backed by official documentation. Terms change; when something here differs from the official source, the official source wins, and this document and its verification date should be updated.

Verified: 2026-10-15 to 2026-10-17 (app modes, Google OAuth and TikTok Sandbox rechecked on 2026-10-17; Facebook Page webhooks and per-platform audience data rechecked on 2026-10-19).

> This document only records the rules and how the workbench handles them; it is not legal advice. Once open-sourced, every self-hoster is the developer of their own apps, and the obligations are theirs (README to be added; see the open-source plan).

## General principles

- Use only official APIs and official keys; no web scraping, no simulated sign-ins.
- Public-facing text (app name, description, website) describes the purpose and features truthfully; never dress up the use case as something it isn't to pass review.
- Privacy policy and terms of service: hosted on the self-hoster's own website (templates in `docs/en/templates/`, notes in `docs/en/compliance-notes.md`). Enter these URLs in every platform console; the data deletion instructions can point to the `#delete` section of the privacy policy.
- Retention of audience comments: 365 days from when the workbench **retrieved** them (`COMMENT_RETENTION_DAYS`), not from when the comment was posted. This is the workbench's own rule (Meta sets no number of days), and the privacy policy states the same period. Implementation: see the data retention section of `docs/en/operations.md`.

## Meta (Facebook / Instagram / Threads)

Sources: [Meta Platform Terms](https://developers.facebook.com/terms/) (2026-02-03 version), [Developer Policies](https://developers.facebook.com/devpolicy/).

| Rule | Content | What the workbench does |
|---|---|---|
| Privacy policy (section 4) | You must have a public privacy policy stating what data you process, why, and how to request deletion. | The self-hoster's own privacy policy page, including `#delete` (template `docs/en/templates/privacy-policy.md`). |
| Data deletion (section 3.d) | Delete data when there is no legitimate use for it and provide a way to request deletion; no number of days is set. | Comments kept 365 days (from retrieval); `scripts/data_retention.py --find-commenter／--delete-contact` handles individual deletion requests. |
| Service providers (section 5.a) | Providers may process data only on your instructions, not for their own purposes, and must agree **in writing**. | The Gemini free tier uses content to improve products → disabled by default, enabled only with `GEMINI_PAID_TIER=true`. TypeSafe's privacy policy says it doesn't train on inputs, but strictly speaking a DPA is still missing (the user decides whether to email them for one). |
| IG user content | Instagram user content may not be imported or backed up without consent. | Only thumbnails of the account's own posts are cached. **Inference**: allowed, but there is no explicit basis. |
| Idle permissions | If a permission or API goes unused for more than 28 days, Meta may disable it. | The hourly sync keeps using the read permissions; the publishing permissions need regular posts. |

### Meta app modes and access levels (verified 2026-10-17)

Sources: [App modes](https://developers.facebook.com/docs/development/build-and-test/app-modes), [Access levels](https://developers.facebook.com/docs/graph-api/overview/access-levels), [Instagram Webhooks](https://developers.facebook.com/docs/instagram-platform/webhooks), [Threads get started](https://developers.facebook.com/docs/threads/get-started).

- **Standard Access**: granted automatically to all business apps, no App Review needed; can only be requested from users who have a role on the app (admins, developers, testers). For a tool used only by yourself, this is enough.
- **Advanced Access**: needed only to serve users without a role; each permission must pass App Review, and Business Verification must be completed.
- **Development mode**: permissions can only be requested from users with a role; the docs give no time limit, but also don't say explicitly that it can be used this way long term.
- **Instagram comment webhook**: the app must be in **Live** mode, `comments` needs **Advanced Access**, and the account must be public. With Standard Access only, IG comment webhooks don't arrive, so comments must be read by periodic API calls. Facebook Page comment webhook: in development mode only test events from the console and events triggered by people with an app role are sent; other people's comments are sent only once the app is live. In addition, the Page must install the app by calling `POST /{page-id}/subscribed_apps?subscribed_fields=feed` with a Page access token (requires `pages_manage_metadata`); subscribing to fields in the console alone isn't enough. The workbench doesn't make this call yet (verified 2026-10-19: [Webhooks](https://developers.facebook.com/docs/graph-api/webhooks), [Webhooks for Pages](https://developers.facebook.com/documentation/pages-api/webhooks-for-pages)).
- **Threads**: testers with a role can authorize at any time without App Review; to serve users without a role, every permission must be reviewed and the app published.

### Meta API specifications (publishing)

- **IG Reels cover** ([IG User Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media)): `cover_url` is for Reels only; a public URL, JPEG, up to 8 MB, sRGB; 9:16 recommended, otherwise the center is cropped, and it is cropped to 1:1 when shared to the feed. When both `cover_url` and `thumb_offset` are given, `cover_url` is used. Stories and carousel children don't support `cover_url`. Implemented in workbench 0048 (PNG converted to JPEG before sending).
- **Facebook regular video cover** ([Page Videos](https://developers.facebook.com/docs/graph-api/reference/page/videos/)): the `thumb` parameter at upload (raw image data); the docs give no format or size limits.
- **Facebook Reels cover** ([Reels Publishing](https://developers.facebook.com/docs/video-api/guides/reels-publishing)): none of the three Reels publishing steps (start / upload / finish) has a cover parameter; at the end the docs point to [Video Thumbnails](https://developers.facebook.com/docs/graph-api/reference/video/thumbnails) to "add a custom cover to Reels".
- **Video Thumbnails**: `POST /{video-id}/thumbnails`, `source` (image file) + `is_preferred=true`; up to 10 MB, same aspect ratio as the video recommended; only for videos associated with a Page. Requires a Page token and `pages_read_user_content`, `pages_manage_engagement`, `pages_show_list`. The docs don't say explicitly that it applies to Reels; the Reels docs just point to it → confirmed by testing. Workbench 0049 uses this endpoint for both regular videos and Reels (not the `thumb` parameter), applying it only after the post succeeds. `pages_manage_engagement` is an optional permission; after enabling it in the Meta console, the account has to be reconnected before it appears in the token (confirmed on 2026-10-17 that the production token lacked it).
- Graph API version: `v26.0` (`oauth.FB`).

## YouTube / Google

Sources: [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies), [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), [YouTube Terms of Service](https://www.youtube.com/t/terms).

| Rule | Content | What the workbench does |
|---|---|---|
| 30-day rule (III.E.4) | Statistics (views, likes) may be stored long term, but every 30 days you must confirm the authorization and the video still exist; other data (titles, thumbnails, comments) may be kept at most 30 days, then deleted or refetched. | The hourly sync refreshes videos; YouTube comments not refetched for 30 days are deleted; data for videos deleted on YouTube is deleted after 30 days. |
| Revoked authorization | Within 7 days of revocation, delete data obtained through that authorization; provide a way to delete stored data, completed within 7 days. | "Disconnect" revokes the authorization and immediately deletes YouTube videos, snapshots, thumbnails, comments and report references (it doesn't delete the videos on YouTube). |
| Privacy policy | State that YouTube API Services are used, and link the [Google Privacy Policy](https://policies.google.com/privacy) and the revocation page `https://security.google.com/settings/security/permissions`. | Included in the privacy policy template. |
| Terms of service | Link the YouTube Terms of Service and state that users agree to be bound by them. | Included in the terms of service template. |
| Minimal scopes | Request only the scopes you need. | `youtube.readonly`, `yt-analytics.readonly`, `youtube.upload`; `youtube` / `force-ssl` are not requested. |

OAuth publishing status (verified 2026-10-17, [OAuth 2.0](https://developers.google.com/identity/protocols/oauth2), [When verification is not needed](https://support.google.com/cloud/answer/13464323)):
- When the consent screen is "External" and the publishing status is **Testing**, refresh tokens **expire after 7 days** (except when only name, email and profile are requested), which means reconnecting every week.
- **Personal use (under 100 users) needs no verification**: once the publishing status is changed to "In production", users can click through the "unverified app" warning when signing in; verification is required only above 100 users. Unverified apps must still follow the API User Data Policy.
- Videos uploaded by unverified API projects are **not** restricted to private (per the `videos.insert` docs, 2026-10-17); the workbench actually uploaded an "Unlisted" video, and its actual status was Unlisted.

API specifications: `videos.insert` uses resumable upload; `thumbnails.set` accepts JPEG / PNG up to 2 MB; custom thumbnails for Shorts are not listed as supported by the API (disabled in the workbench). Quota: `videos.insert` has its own daily upload allowance; other reads share `youtube.quota` (see `docs/en/operations.md`).

## TikTok

Sources: [Developer Terms of Service](https://www.tiktok.com/legal/page/global/tik-tok-developer-terms-of-service/en) (2025-12-26 version), [App review guidelines](https://developers.tiktok.com/doc/app-review-guidelines), [Content sharing guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines), [Content Posting API get started](https://developers.tiktok.com/doc/content-posting-api-get-started), [Media transfer guide](https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide), [Upload video (inbox)](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video), [Get post status](https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status), [Token management](https://developers.tiktok.com/doc/oauth-user-access-token-management), [Video list](https://developers.tiktok.com/doc/tiktok-api-v2-video-list). The workbench's full plan is in `docs/en/tiktok-plan.md`.

### Developer terms

| Rule | Content | What the workbench does |
|---|---|---|
| Call volume (III.3.g) | No excessive or abusive use; posting-related APIs at most 6 calls per minute. | Hourly sync; sending happens only at the scheduled time. |
| Watermarks (III.3.t) | Don't overlay brands, logos or watermarks on users' videos. | Video files are not modified. |
| Consent | Don't upload any content before the user explicitly consents. | Content is sent only after the user confirms publishing or scheduling. |
| Privacy disclosure (III.2.c) | Fully and accurately disclose privacy practices. | The self-hoster's privacy policy page. |
| Profiles (III.3.h) | Don't collect other people's data or build profiles or databases. | Only the user's own account is read; comments are not read. |
| Endorsement (III.3.o) | Don't imply a partnership with or endorsement by TikTok. | The app name doesn't contain TikTok (the author's own is "ruidefilm Workbench"). |
| Public statements (X) | Without written consent, don't make public statements about your relationship with TikTok or your access to developer services. | **Inference**: when introducing it, use feature descriptions such as "sends to the inbox through the official API", not "TikTok partner / officially approved". |
| Commercial use (III.3.c) | Without written consent, don't use for commercial advertising, solicitation or spam. | Posting your own work is what the Content Posting API is meant for; sponsored content must be disclosed per TikTok rules. The line is blurry, **unconfirmed**. |
| Authentic identity (III.3.q) | Don't use a false identity. | Don't apply for the Business API in a company's name. |
| Open source (III.3.e) | Don't subject TikTok developer services to open-source license obligations. | Only the API is called; no TikTok SDK or sample code is included; check again when open-sourcing. |
| Security incidents (III.2.f) | When compromised, disconnect immediately and report to TikTok. | The operator's responsibility. |
| Termination (VI) | When developer services end, delete all data obtained through the API. | "Disconnect" revokes the authorization and deletes TikTok data. |
| App name (review guidelines) | Must not mention a social media company, must match the app / website name, and can't just describe a feature. | Use your own website or brand name, for example "〈brand〉 Workbench". |

### Review and publishing limits

- **Sandbox** ([docs](https://developers.tiktok.com/doc/add-a-sandbox)): "a restricted environment for trying out an integration without review"; up to 5 sandboxes, each with up to 10 target accounts; the docs give no expiry date. It **doesn't say whether it can be used long term for real use**; it is positioned for testing. In Sandbox, the Content Posting API isn't available for public videos. The workbench currently runs on Sandbox, which is a gray area (inference: the worst case is the app being restricted, not the TikTok account being banned, because you publish the video yourself in the app).
- **Unreviewed (Sandbox)**: Direct Post can only use `SELF_ONLY`, the posting account must be private, and at most 5 users can post within 24 hours. Inbox upload (`video.upload`) works, with the user completing the post in the app.
- **General rules in the App review guidelines** (checked 2026-10-17): "Apps must not be for private or personal use", "Apps that are still in development or testing will not be approved"; request only the permissions you need, and every product and permission must be shown in the demo video; the demo video must record the full flow in Sandbox, and the domain must match the website you entered. The guidelines themselves have no list of Content Posting API use cases (that list is in the content sharing guidelines). **Inference**: a workbench used only for your own or your clients' accounts counts as "private use", so a review submission (whether or not it requests Direct Post) is likely to be rejected.
- **Direct Post review**: the use case must "help real creators publish original content" and serve a broad user base. Explicitly **not accepted**: "tools that upload content to accounts you or your team manage", testing only, and reposting content from other platforms. The review form asks for estimated usage, which sets the creator cap per 24 hours. **Inference**: the workbench's current positioning (managing your own accounts) won't pass; only a product genuinely used by many creators could be submitted truthfully.
- **Direct Post UI requirements** (needed only for review): read creator_info every time and show the nickname, check length against `max_video_post_duration_sec`, privacy dropdown with no default, comment / duet / stitch unchecked by default, music usage confirmation, commercial content disclosure, preview, and a notice that processing takes a few minutes with status tracking. The demo video and the 2–6 week review period appear only in third-party articles, **unverified**.
- **Inbox upload**: the init endpoint has no caption field (captions can only be pasted in the app) and no cover field (the cover is chosen in the app; `video_cover_timestamp_ms` belongs to Direct Post only). At most 5 pending within 24 hours (`spam_risk_too_many_pending_share`), about 15 posts per account per day.
- **Can inbox uploads carry a caption** (rechecked 2026-10-17): the body of the video inbox init has only `source_info` (`source`, `video_size`, `chunk_size`, `total_chunk_count` or `video_url`), no `post_info` / `title` / `description`; the description of the `video.upload` scope also says "sent to the creator's account as a draft, then edited and posted in TikTok". The only ways to carry text are: Direct Post (`post_info.title`, needs `video.publish` + review), photo posts (`post_info.title` / `description` in `/v2/post/publish/content/init/`, but photos must be pulled from a verified domain), and Share Kit (native iOS / Android SDK; the docs only mention partner hashtags, no caption field, and a web tool can't use it). Tested: on 2026-10-17 an unreviewed Sandbox app successfully sent a video to the inbox.
- **Video specs**: API uploads up to 10 minutes; up to 64 MB can be sent in one chunk, otherwise in chunks (the workbench uses 10 MB). `creator_info`, which looks up per-account limits, needs `video.publish`, which the workbench doesn't request.
- **Photo posts**: can only be downloaded from public URLs on a verified domain → not supported by the workbench, which shows "Only videos can be published. Upload photo posts in the TikTok app."
- **Tokens**: access token 24 hours; refresh token 365 days, rotated on every refresh.
- **Data**: the Display API video list returns only public videos (with counts such as views); follower count comes from user/info. Private videos aren't in the list, so "deleted or made private" are handled together.
- **Covers** ([Query Videos](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query), checked 2026-10-19): `POST /v2/video/query/` needs `video.list`, takes at most 20 video IDs per call and returns only the authorized account's own videos; the docs say it can be used to "refresh the expiry of cover URLs" (without saying how long). The workbench's thumbnail cache uses it to get `cover_image_url` and immediately shrinks it to a JPEG file. The CDN domains aren't documented; the workbench currently allows `tiktokcdn.com` / `tiktokcdn-us.com` / `tiktokcdn-eu.com`, **not tested**.
- **Comments**: only TikTok API for Business can read them; applicants must be a company using a company-domain email, and individual developers aren't accepted → the workbench doesn't read TikTok comments.

## Audience data (per platform, verified 2026-10-19)

| Platform | Officially available | Conditions | What the workbench does |
|---|---|---|---|
| Instagram | `follower_demographics` (age, gender, country, city; `timeframe` required); `online_followers` (online followers per hour, kept only 30 days) | `instagram_manage_insights`; at least 100 followers. `online_followers` appears only in the limitations section of the official page, not in the metrics table; **unverified** whether it will be deprecated | Fetched once a day; see audience analysis in `docs/en/architecture.md` |
| Facebook Page | Only location remains: `page_follows_country` / `page_follows_city` | `read_insights`. Age and gender (`page_fans_gender_age`, `page_follows_gender_age`) were deprecated on 2024-03-14 with no replacement; `page_fans_city／country` deprecated on 2025-11-15 | Shows location only and explains that age and gender were deprecated |
| Threads | `follower_demographics` (country, city, age, gender; one at a time) | `threads_manage_insights`; at least 100 followers; since / until not supported. No online-time metric | Fetched once a day |
| YouTube | YouTube Analytics: `viewerPercentage` by `ageGroup`, `gender`; `views` by `country` | `yt-analytics.readonly`. Age and gender cover signed-in viewers only. Studio's "When your viewers are on YouTube" isn't available through the API (**inference**: the official dimension list has no matching item) | Last 28 days |
| TikTok | The Display API has no audience data; the Business API (business accounts) has age, gender, location and active hours | The Business API needs a separate application and review, and is limited to business accounts | Not done; the UI explains why |
| LINE | The Messaging API has demographics for the official account's friends (`/v2/bot/insight/demographic`) | Requires connecting the brand's official account; the workbench uses LINE only for notifications (`AGENTS.md`) | Not done; the UI explains why |

Sources: [IG account Insights](https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights), [Deprecated Page Insights metrics](https://developers.facebook.com/documentation/pages-api/platforminsights/page/deprecated-metrics), [Threads Insights](https://developers.facebook.com/docs/threads/insights/).

## Video watch metrics (per platform, verified 2026-10-23)

| Platform | Officially available | What the workbench does |
|---|---|---|
| Instagram Reels | Media insights: `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time` (milliseconds, officially marked in development), `reels_skip_rate` (share who swipe away in the first 3 seconds; an estimate, in development). No retention curve | The three are combined into one call (the average watch time call was already being made, so no extra Meta quota); if the whole batch is rejected, it falls back to reading only average watch time, with one extra call |
| Facebook video / Reels | Post insights: `post_video_avg_time_watched`, `post_video_view_time` (milliseconds), `post_video_retention_graph` (retention share in 40 equal segments). What was deprecated on 2026-06-15 are unique-count metrics such as `post_video_views_unique`; these three aren't on the deprecation list | Same as above, three in one call; the retention curve is shown in "Watch performance" |
| YouTube | Analytics: `averageViewDuration`, `estimatedMinutesWatched`, `averageViewPercentage`; the retention curve `audienceWatchRatio` needs a separate report call per video | Average view percentage comes in the same call as the existing report; the retention curve isn't fetched for now (one extra call per video would eat into the 420-call cap per round) |
| Threads | Post insights only have views, likes, replies, reposts, quotes, shares | No watch time or retention; the UI explains this |
| TikTok | The Display API `video/list` only has view / like / comment / share counts and duration; watch time and completion rate need the Business API (business accounts, separate review) | Not done; the UI explains this |

Sources: [IG Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights), [Page / Post Insights](https://developers.facebook.com/docs/graph-api/reference/insights), [YouTube Analytics metrics](https://developers.google.com/youtube/analytics/metrics).

## AI and other service providers

| Service | Rule | What the workbench does |
|---|---|---|
| Gemini API ([Additional terms](https://ai.google.dev/gemini-api/terms)) | The free tier uses submitted content to improve Google products and it may be reviewed by humans, so don't send personal information; the paid tier doesn't. | Disabled by default; only `GEMINI_PAID_TIER=true` allows it to process platform data. From 2026-10-01 to 02 the free tier was used to process redacted IG comments; this can't be undone. |
| Anthropic consumer plans ([Updates to consumer terms](https://www.anthropic.com/news/updates-to-our-consumer-terms)) | Free / Pro / Max (including Claude Code) train on conversations when the user allows it, and keep data for 5 years. | Comments an agent reads through MCP enter the conversation → users need to turn off "Help improve Claude". |
| ChatGPT / Codex | Should have similar data controls. | Menu location and terms **unverified**. |
| TypeSafe ([Privacy policy](https://typesafe.ai/legal/privacy-policy), 2025-11-19 version) | Doesn't train or fine-tune on input content; shares it only with service providers. | Consistent with Meta's intent, but no written DPA. |
| LINE ([Developers Agreement](https://terms2.line.me/LINE_Developers_Agreement?lang=en)) | Process data only to the extent necessary. | Only the first 180 characters of redacted comments are sent to your own notification group; Push quota is checked first. |
| All cloud models | — | Personal data is always redacted by `redact.py` before sending. |
