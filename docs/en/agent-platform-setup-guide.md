# Platform setup guide for AI agents (browser assistance)

> **Language / 語言 / 语言 / 言語**: [繁體中文](../zh-tw/agent平台串接引導.md) | [简体中文](../cn/agent平台对接引导.md) | English | [日本語](../jp/エージェント向けプラットフォーム連携ガイド.md)
>
> **Agent: before you start, work out which language the user speaks** (from the messages they write to you; if they have not written yet, from the system locale). If it is not English, read the matching version above instead and use that language with the user throughout. If none of the four matches, follow this English version but still reply in the user's language.

This document is written for an **AI agent**. After the user first sets up the workbench, connecting their Facebook Page, Instagram, Threads, YouTube and TikTok requires creating their own apps in each platform's **developer console** first. The steps are tedious, so you can operate the browser and fill in the settings for them, while they do only the parts they must do in person.

- Prerequisite: Stages 1–5 of [`agent-install-guide.md`](agent-install-guide.md) are done (the workbench opens at the internal https address, and the privacy policy and terms of service are public).
- Follow this document when you can operate a browser (for example Claude in Chrome, Claude's built-in browser, or Codex's browser tool); when you can't, walk the user through the same steps in text so they click through themselves.
- The steps match the workbench's Settings → Platform connections → "Setup guide" (source `frontend/src/platformGuides.ts`, which uses the wording of the actual console screens); permissions follow `backend/app/services/oauth.py`; rules and sources are in [`platform-policies.md`](platform-policies.md) (platform policies). If the three disagree, the code wins; report the difference to the maintainer.

UI labels below are quoted from the English interfaces of the workbench and the platform consoles.

## Boundaries (always follow)

You may: navigate, click and fill in **non-secret** fields in developer consoles (app name, use cases, callback URLs, permissions, scopes, enabling APIs, brand name and contact email, category, description, privacy policy and terms of service URLs), and click "Save".

You may not:

1. **Sign-ins, passwords, 2FA and security checks** are always entered by the user. When you reach a sign-in page or "Enter your password", stop and ask the user to do it, then continue once they're done.
2. **Don't touch secrets**: don't click "Show" on an app secret / client secret, don't copy it, read it out, write it into the chat or a file, or screenshot a screen showing it. The user pastes the app ID and secret into the matching card in the workbench's Settings → Platform connections themselves (stored encrypted), not into the chat.
3. **Don't click the workbench's "Connect … account", don't click through any OAuth authorization / consent screen** for the user, and don't accept developer terms on their behalf (for example signing in and agreeing under TikTok "Target Users").
4. **Don't submit for review or change live mode**: don't submit Meta App Review or Business Verification, Google app verification or TikTok Production review; don't switch the Meta app to Live. Keep TikTok Direct Post off.
5. **Don't post, reply to comments or turn on any sending or publishing switch**; no web scraping, no unofficial APIs. Use the browser only on developer console settings pages.
6. **Ask first before buttons that create resources or accept terms** (creating an app, creating a Google Cloud project, Google "Publish app"), and click only after the user agrees.
7. **Don't guess when the screen differs from this document**: consoles change often. First show the user a screenshot and explain the difference, check the official docs if needed, then decide the next step.
8. **Stop if the use case doesn't fit**: if the user wants to manage clients' accounts, manage brands of several different companies or open sign-up to others, first explain that this isn't supported and may break platform rules (see [`compliance-notes.md`](compliance-notes.md)), and let the user decide.

## Before you start

1. Work in a new tab; don't touch the user's existing tabs.
2. Ask which platforms to set up and confirm the account types: Facebook needs a **Page admin**; Instagram needs a **professional account linked to that Page**; Threads works with a personal account; YouTube needs the Google account that owns the channel (for a brand channel, choose the Brand Account); TikTok works with a personal account.
3. Get the **callback URL**: ask the user to open the workbench's Settings → Platform connections, press the copy button in that platform card's "Setup guide" and paste it to you (the callback URL isn't secret); or open that dialog yourself in the browser and read it. The format is `<internal https URL>/api/oauth/<meta|threads|youtube|tiktok>/callback`. If it doesn't start with `https://`, stop: the workbench must be opened at the internal https address to connect.
4. Have the **public URLs of the privacy policy and terms of service** ready (TikTok Sandbox requires them too).
5. For the **app name**, use the user's website or brand name (for example "〈brand〉 Workbench"); it must not contain platform names such as TikTok, Facebook or Instagram, and shouldn't just describe a feature.

After each step, take a screenshot to confirm and tell the user in one sentence what you did; compare callback URLs and permissions character by character.

## Meta (Facebook Page + Instagram)

Console: <https://developers.facebook.com/apps/>

1. (Ask first) "Create app" <https://developers.facebook.com/apps/creation/>, named after the brand; for the use case, pick one related to Pages, and click "Next" for the rest.
2. "App settings → Basic": enter the privacy policy URL, terms of service URL, data deletion instructions URL (can point to `#delete` in the privacy policy), category and contact email, then save. Ask the user to paste the app ID and secret into the "App ID" and "App secret" fields of the workbench Meta card themselves.
3. In "Facebook Login → Settings" (apps created through the use-case flow show "Facebook Login for Business → Settings"), paste the meta callback URL into "Valid OAuth Redirect URIs" and click "Save changes".
4. In "Use cases → Customize → Permissions and features", find each of these and click "Add" (there's no add-all option; use in-page search): `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`, `pages_manage_metadata`, `pages_manage_posts`, `read_insights`. Optional: `pages_manage_engagement` (for custom video covers; without it only the cover feature is disabled).
5. With Instagram: on the same page also add `instagram_basic`, `instagram_manage_comments`, `instagram_manage_insights`, `instagram_content_publish`. If they aren't on that page, add "Manage messaging & content on Instagram" under "Use cases", choose "API setup with Facebook Login", then add them.
6. Hand over to the user: in the workbench they click "Connect Meta account", and on the authorization screen click "Edit settings" (or "Edit access") to select the Page and Instagram.

For personal use, Standard Access is enough and **no review is needed**; whoever connects must have a role on the app.

### Meta webhook (optional; ngrok must be set up first and WEBHOOK_PUBLIC_URL must have a value)

1. The verify token is set by the user themselves in the workbench Meta card under "Manual setup (advanced) → Webhook verify token", and entered in the console by them as well; you don't handle it.
2. In the console sidebar, under "Webhooks" choose "Page" → "Subscribe to this object", set the callback URL to `<WEBHOOK_PUBLIC_URL>/webhook/meta-inbound`; after the user enters the token, click "Verify and save". Subscribe to the "feed" field. With Instagram, switch to the "Instagram" object, use the same URL and token, and subscribe to "comments".
3. Remind the user: in development mode only test events and comments by people with a role are received; the Instagram comment webhook needs Live + Advanced Access and is out of scope here. Without a webhook, the workbench still fetches comments itself every hour.

## Threads (same Meta app)

1. Open the app → under "Use cases" add "Access Threads API" → "Customize → Settings".
2. Ask the user to paste the "Threads app ID" and "Threads app secret" (a different pair from Facebook's) into the workbench Threads card themselves.
3. On the same page, paste the threads callback URL into "Redirect Callback URLs" and save. If the uninstall / delete callbacks are required, ask the user what to enter first (the privacy policy URL works).
4. Under "Permissions and features", add each of: `threads_content_publish`, `threads_manage_replies`, `threads_manage_insights`, `threads_read_replies` (`threads_basic` is already added by default).
5. In "App roles → Roles → Add People", choose "Threads Tester" and enter the Threads username the user gives you.
6. Hand over to the user: in the Threads mobile app, go to "Settings → Account → Website permissions → Invites" and tap "Accept", then click "Connect Threads account" in the workbench.

## YouTube (Google Cloud)

1. (Ask first) Create a project <https://console.cloud.google.com/projectcreate>, any name; confirm this project is selected at the top.
2. Enable two APIs (click "Enable" on each): [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com), [YouTube Analytics API](https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com).
3. In [Branding](https://console.cloud.google.com/auth/branding) click "Get started": app name, user support email; for "Audience" choose "External"; contact email; ask before ticking the agreement, then click "Create". You can add the home page, privacy policy and terms of service URLs.
4. (Ask first) In [Audience](https://console.cloud.google.com/auth/audience) click "Publish app" to switch to "In production", otherwise authorization expires every 7 days. This is **not** submitting for verification: personal use under 100 users needs no verification, so don't click any "Submit for verification".
5. [Data access](https://console.cloud.google.com/auth/scopes) → "Add or remove scopes" → paste these three lines into "Manually add scopes", then click "Add to table" → "Update" → "Save":
   - `https://www.googleapis.com/auth/youtube.readonly`
   - `https://www.googleapis.com/auth/yt-analytics.readonly`
   - `https://www.googleapis.com/auth/youtube.upload`

   Don't add `youtube` or `youtube.force-ssl`.
6. In [Create client](https://console.cloud.google.com/auth/clients/create) choose "Web application", paste the youtube callback URL into "Authorized redirect URIs", and click "Create".
7. **Stop immediately**: the secret is shown only this once. Ask the user to paste the "Client ID" and "Client secret" into the workbench YouTube card themselves (they can click "Download JSON" first to keep a copy); only after the dialog is closed do you continue taking screenshots or operating.
8. Hand over to the user: click "Connect YouTube account" in the workbench; when "Google hasn't verified this app" appears, they click "Advanced → Go to (app name)" and tick all permissions.

## TikTok (Sandbox only)

Console: <https://developers.tiktok.com/> ("Developer Portal" at the top right)

1. (Ask first) Create an app; the name **must not contain "TikTok"**; use the brand name.
2. Switch to "Sandbox" at the top of the page and create one.
3. Under "Add products", add **Login Kit** and **Content Posting API**; **keep Direct Post off**.
4. For Login Kit's "Redirect URI", choose Web and paste the tiktok callback URL.
5. Under "Scopes", use "Add scopes" to add exactly these four: `user.info.basic`, `user.info.stats`, `video.list`, `video.upload`. Don't add `video.publish`.
6. Required fields in Basic information: App icon (ask the user for the image file), Category, Description (describe it truthfully, for example "sends my own videos to my TikTok inbox and reads public video stats for my own account"), and the terms of service and privacy policy URLs. Click "Apply changes"; it's done only when there is no red text. Don't click "Verify domains".
7. Hand over to the user: under "Target Users" → "Add account", they sign in to TikTok and agree to the developer terms (it may take up to 1 hour to appear).
8. Hand over to the user: they paste the Client key and Client secret from the Sandbox "Credentials" into the workbench TikTok card themselves, then click "Connect TikTok account".

**Never**: submit for Production review (TikTok doesn't accept private or self-use tools), turn on Direct Post, or apply for TikTok API for Business (companies only). Remind the user: videos only go to inbox drafts (at most 5 pending within 24 hours), the caption and cover are handled in the app, choose "Everyone" when posting, then confirm from a signed-out browser that it's public.

## Wrapping up

When each platform is done, list for the user: the callback URLs set, the permissions added, and what they still need to do themselves (paste secrets, click connect, accept invitations, Target Users). It's complete when the workbench card shows the account name and "Connected"; if the card shows missing permissions, go back to the console to add them and ask the user to reconnect.

Common errors:

- "URL mismatch" / `redirect_uri_mismatch`: paste the whole callback URL; no extra slashes and don't change it to http.
- The Page isn't found during authorization: click "Edit settings" on the authorization screen to select it, and the person must be a Page admin.
- Threads says the account isn't a tester: accept the invitation in the Threads app.
- The "Connect" button is grayed out: reopen the workbench at the internal https address.
- TikTok "Apply changes" shows red text: App icon, Category, Description and both policy URLs are required, and the name must not contain TikTok.
