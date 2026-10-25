# TikTok plan (first version)

> **Language / 語言 / 语言 / 言語**: [繁體中文](TikTok規劃.md) | [简体中文](TikTok规划.md) | English | [日本語](TikTok計画.md)

Finalized in the planning Q&A on 2026-10-16. Official limits follow the official documentation checked on 2026-10-16; anything unconfirmed is listed under "To confirm by testing".

## Premises

- Use TikTok for Developers (developers.tiktok.com), **without submitting for review**. Review involves product positioning and is folded into the open-source planning for a later decision.
- One TikTok connection and one account for the whole site; multiple accounts are left to the multi-brand plan. The account type does not affect which APIs are available, so there is no need to switch to a business account.
- After open-sourcing, each user creates their own TikTok app, the same as for Meta, Threads and YouTube.
- Only official APIs are used; data the official APIs do not provide is not obtained through scraping or unofficial APIs.

## Official limits (basis for decisions)

- An unaudited app can publish directly only as `SELF_ONLY`, and the posting account must be private; public posting requires passing review. Review does not accept apps for private or personal use. Sources: <https://developers.tiktok.com/doc/content-sharing-guidelines>, <https://developers.tiktok.com/doc/app-review-guidelines>
- Photo posts can only use `PULL_FROM_URL`, and the URL must belong to a verified domain; videos can use `FILE_UPLOAD`, uploaded directly by the backend. Source: <https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide>
- Sending to the inbox (`video.upload`) allows at most 5 pending videos within 24 hours; the length limit varies by account, as given by creator_info's `max_video_post_duration_sec`. Sources: <https://developers.tiktok.com/doc/content-posting-api-reference-upload-video>, <https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info>
- The post status query returns a public post ID only when the post is public and the app has been audited. Source: <https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status>
- The access token lasts 24 hours and the refresh token 365 days; the refresh token returned on renewal may change. Source: <https://developers.tiktok.com/doc/oauth-user-access-token-management>
- Display API `video.list` returns only public videos. Source: <https://developers.tiktok.com/doc/tiktok-api-v2-video-list>
- Reading comments is offered only by the Accounts API of TikTok API for Business. Developer registration requires an email on a company domain and a company website (personal websites and individual developers are not accepted), and the Accounts API application form requires the full company name as on the registration documents plus business verification (registration documents or a verified Business Center). Sources: <https://business-api.tiktok.com/portal/docs/register-as-a-developer/v1.3>, <https://business-api.tiktok.com/portal/docs/accounts-api/v1.3>

## Connecting the account and tokens

- Scopes: `user.info.basic`, `user.info.stats`, `video.list`, `video.upload`.
- The redirect URI first uses the workbench's Tailscale https URL; if TikTok does not accept it, switch to the desktop-mode redirect `127.0.0.1` (PKCE, with the code challenge as SHA256 hex), in which case connecting must be done on the computer running the workbench.
- The backend renews the access token automatically before calls; the user does not need to do anything. 14 days before the refresh token expires, or when renewal fails, a LINE notification asks to reconnect; the card shows connected / expiring soon / invalid and the expiry date in Taipei time.

## Data

- Every hour, sync public videos with their views, likes, comment counts and share counts, plus the follower count.
- When a full list is obtained, videos missing from it are marked "deleted or made private" and hidden from Post analytics; when the list is incomplete or empty, no judgment is made.
- Merged into Post analytics and the Dashboard; performance the official API does not provide can be imported from a CSV exported from TikTok Studio.
- Ideation gets no TikTok tab: ideation is based on comments, and TikTok has no comment source.

## Publishing

- Videos only, sent to the TikTok inbox (`MEDIA_UPLOAD`); the user edits and posts in the app. The workbench sends at the scheduled time and does not decide when it goes public.
- When TikTok is checked for a photo post, it is blocked with the notice “Only videos can be published. Upload photo posts in the TikTok app.”
- Part of the shared caption workflow; the TikTok tab can override the caption. If the API cannot carry the caption, Publish history offers “Copy caption”.
- The length limit is checked with creator_info when scheduling and before sending; when the inbox is full, the error code at send time explains the reason and the send can be retried.
- Status is tracked by polling, without TikTok Webhooks, and no paths are added to the public entry point. The final status is "sent to TikTok inbox", changed to “Published in app” when that can be detected; without a post ID no link is attached, and videos that appear later are not matched automatically.

## Comments

- Not implemented in the first version; only a notice: “Reading TikTok comments requires applying for TikTok API for Business as a company (individual developers can't apply)”. Locations: the “Comments (optional)” block of the TikTok card in Platform connections, the “Read comments (companies only)” section of the setup guide, and the comments area of TikTok videos in Post analytics.
- Direction for later, once a company identity is obtained and the application is approved: the Business API handles comments only, while publishing and data still go through TikTok for Developers; read only, no replies; fetch hourly, no Webhooks; the TikTok tab appears in Ideation only once connected.

## Not doing

Direct public posting (requires review), photo posts (require a verified domain), reading and replying to comments (requires a company identity), unofficial APIs and scraping.

## Delivery order

Each step moves on only after its acceptance check passes.

1. Rewrite the TikTok setup guide (including the comments notice) and help the user create the app. (Completed 2026-10-16; the Sandbox has been created following the guide.)
2. Connect the account, automatic token renewal, expiry reminders; add the “Comments (optional)” notice to the card. (Deployed 2026-10-16; connected successfully on the live system, confirming the Tailscale https URL works as the redirect URI.) The redirect URI could only be tested once the workbench had an authorization route, so this was swapped with the original step 3: finish the connection feature first, then test the redirect URI and read permissions after deployment.
3. Testing (see the next section); the inbox and caption items are left for testing during step 5, publishing.
4. Data sync, Post analytics (including the comments notice), Dashboard. One `video.list` per hour (20 videos per page, at most 50 pages) writes both posts and due performance snapshots, without querying each video; one `user.info` per day for follower_count. Only a full, non-empty list marks vanished videos as deleted or made private and hides them; the TikTok tab on the Publish page changes to "publishing not yet available".
5. Publishing: send videos only to the inbox (FILE_UPLOAD via `POST /v2/post/publish/inbox/video/init/`, one chunk up to 64 MB, otherwise sequential PUTs of 10 MB chunks). The publish_id is saved first; a retry checks the status first and does not resend if it is already in the inbox. After sending, wait up to 60 seconds for SEND_TO_USER_INBOX, then track every 10 minutes for 7 days to see whether it becomes PUBLISH_COMPLETE. The inbox API does not accept a caption (verified), so Publish history offers “Copy caption”. The length limit is fixed at 10 minutes per the official media transfer guide: creator_info, which looks up the per-account limit, requires video.publish, which the first version does not request.

## To confirm by testing

- Whether the Tailscale https URL can be used as a web redirect URI.
- Whether an unaudited app can send videos to the inbox (to be tested after step 5 is deployed, with a test video the user agrees to).
- Whether the status becomes `PUBLISH_COMPLETE` after the user posts in the app (the official status doc says it does; to be tested).
- Whether a caption can be sent to the inbox: the official init endpoint has no caption field, so it definitely cannot (verified 2026-10-17).
