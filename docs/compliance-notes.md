# Compliance notes for self-hosters

> **Language / 語言 / 语言 / 言語**: [繁體中文](合規須知.md) | [简体中文](合规须知.md) | English | [日本語](コンプライアンスの注意事項.md)

When you self-host this workbench, you are the **developer** of your own Meta, Google and TikTok apps. The obligations under each platform's terms fall on you, not on this project. This checklist covers what you must do yourself before and after self-hosting; the source and verification date of each rule are in [`platform-policies.md`](platform-policies.md) (platform policies).

> This document summarizes platform rules and how the workbench handles them; it is not legal advice. Terms change; the latest official documents win.

## First, confirm the use case: only for yourself or your own brand

The workbench is designed for **one brand, self-hosted by the brand owner, managing their own accounts**. The following uses are not supported and may also break platform rules:

- **Managing accounts for others**: running accounts on behalf of clients or other companies. For people without an app role to use it, Meta requires passing App Review for Advanced Access and completing Business Verification; TikTok explicitly does not accept "tools that upload content to accounts you or your team manage".
- **Multiple brands**: one workbench managing brands of different entities (different companies). Not supported for now.
- **Public service**: opening sign-up to other people.

Team members of the same brand each signing in to the workbench is fine: the platforms only care about "who authorized the app", and that person must have a role (admin, developer or tester) on your Meta app. Create the app under the entity that owns the brand: a personal brand uses a personal account, a company brand is set up by the company, not under an employee's personal developer account.

## 1. Privacy policy and terms of service (required by every platform)

Put two public pages on your own website, then enter their URLs in each platform console. Templates are in [`templates/`](templates/): replace `{{…}}` with your details and delete the sections you don't use. You can also give the templates, your `.env` settings and these notes to your own AI and have it write them based on your actual setup.

The policy must truthfully reflect your setup and include at least:

- What data is collected: your own accounts' posts and performance, and **public comments other people leave on your posts** (name, account identifier, content).
- Processors: TypeSafe (comment classification), the AI service you configured, the AI agent you connect, LINE (urgent notifications). Delete any you don't use.
- Retention: comments for `COMMENT_RETENTION_DAYS` days from retrieval (default 365); the YouTube 30-day rule.
- Deletion requests: commenters can request deletion, handled within 7 days.
- What YouTube requires: state that YouTube API Services are used, and link the [Google Privacy Policy](https://policies.google.com/privacy) and the revocation page `https://security.google.com/settings/security/permissions`.
- The terms of service must state that "users agree to be bound by the [YouTube Terms of Service](https://www.youtube.com/t/terms)".

## 2. Platform console settings

### Meta (Facebook / Instagram / Threads)

- The app name must not contain a platform name and must not suggest a partnership with Meta.
- Under "Basic", enter the privacy policy URL, terms of service URL and data deletion instructions URL (for example `/privacy#delete`).
- For personal use, **Standard Access** is enough and no App Review is needed; whoever authorizes must have a role on the app. Add the Threads account as a tester and accept the invitation in Threads.
- With Standard Access only, Instagram comment webhooks don't arrive (they need Live mode + Advanced Access); the workbench reads comments through periodic API calls instead, so this doesn't affect use.
- If a permission goes unused for more than 28 days, Meta may disable it.

### Google (YouTube)

- Change the consent screen publishing status to **In production**. While it stays "Testing", refresh tokens expire after 7 days and YouTube has to be reconnected every week.
- Personal use under 100 users doesn't need Google verification; during authorization you'll see an "unverified app" warning, just click "Continue". Verification is required only above 100 users.
- Under "Branding", enter the app home page, privacy policy and terms of service URLs.
- The workbench requests only `youtube.readonly`, `yt-analytics.readonly` and `youtube.upload`; don't add broader scopes yourself.

### TikTok

- The app name **must not contain "TikTok"**, must match your website name and can't just describe a feature.
- The workbench can only use **Sandbox**: videos are sent to your TikTok as drafts (an inbox notification), and you add the caption and post in the app. The inbox API doesn't accept captions and can't set a cover.
- TikTok officially positions Sandbox as a test environment (up to 10 target accounts). Long-term real use isn't explicitly allowed; it is a gray area, so judge for yourself.
- Without review, Direct Post (`video.publish`) can only post as "Only you", and the posting account must be private; review doesn't accept tools for managing your own accounts. Reading comments requires applying for TikTok API for Business as a company, so the workbench doesn't read TikTok comments.
- When introducing the tool, describe its features (for example "sends to TikTok drafts through the official API"); don't present it as partnered with or approved by TikTok.

### LINE

- Use it only for notifications to your own group; Push messages have a monthly quota, so check your plan first.

## 3. AI and data processors

- Text sent to cloud models is first redacted of personal data by `redact.py`; don't turn this off.
- **Gemini paid tier only**: the Gemini API free tier uses submitted content to improve Google products, which violates Meta's requirements for service providers. So by default the workbench doesn't let Gemini process platform data; set `GEMINI_PAID_TIER=true` only after the Google Cloud project has billing attached. The Anthropic and OpenAI APIs don't train on API data by default, so no extra setting is needed.
- **Agents signed in with a personal subscription must have training turned off**: comments an agent reads through MCP enter the conversation. If the agent signs in with a personal subscription (for example Claude Code on Claude Pro / Max, or ChatGPT Plus), turn off "train models on conversations" in that service's privacy settings; an agent using an API key doesn't need this (Gemini still needs the paid tier).
- Meta requires service providers to agree **in writing** to process data only on your instructions. When needed, ask providers such as TypeSafe for a data processing agreement (DPA).

## 4. After deployment

1. Preview how many rows data retention would delete (read only): `uv run --project backend python scripts/data_retention.py`.
2. After confirming, turn on daily deletion: the same command with `--enable`.
3. When a commenter asks for deletion: find them with `--find-commenter`, preview with `--delete-contact`, then add `--apply` to delete after confirming.
4. "Disconnect" revokes the authorization and deletes that platform's synced data (YouTube, TikTok); content on the platform is not affected.
5. The workbench UI is open only to the local machine and the private network (Tailscale); don't expose the UI directly to the public internet. The only public entry points are signature-verified webhooks and time-limited media links.
6. In a security incident (computer or account compromised), first disconnect each platform and rotate the keys; TikTok's terms require disconnecting immediately and reporting.

## 5. Open-source license and TikTok

The workbench calls each platform's official API over HTTP only and includes no TikTok SDK or sample code, so TikTok Developer Terms III.3.e (don't subject TikTok developer services to open-source license obligations) is not affected by this project's license. If you add a platform SDK in your own fork, check license compatibility yourself.
