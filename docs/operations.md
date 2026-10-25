# Deployment and operations

> **Language / 語言 / 语言 / 言語**: [繁體中文](部署與維運.md) | [简体中文](部署与运维.md) | English | [日本語](デプロイと運用.md)

Paths for the database, exports, logs, backups and the MCP audit log come from configuration; nothing depends on the developer's disk or host name. `.env.example` is the reference for configuration fields; credentials are filled in only on the local machine. Design rules for each feature are in [architecture](architecture.md); this page records only operating steps. Acceptance details for each change are kept in the git history and are no longer written here.

## Deployment order

A development session does not stop or restart running services, does not change the live send switches, and does not send platform messages. An operator with the right permissions runs the following after checking the working tree and the rollback data:

1. **Back up**: run `./scripts/backup.ps1` first, and separately make a secure backup of `.env`, the service deployment configuration and the old version; check that the database and exports are readable, and record each account's send switch and `publishing.enabled`. Backups contain historical content and secrets, are restricted to the operator, and are never included in the open-source archive.
2. **Stop services**: run `./scripts/stop-all.ps1`, and confirm that the PIDs belong to this project and that the service ports are released. If permissions are insufficient, stop the deployment; do not start a second set of receiving services.
3. **Schema upgrade**: run `uv run alembic upgrade head` in the backend directory. Pre-checks and downgrade limits for individual migrations are listed under "Migration notes" below.
4. **Start**: first `npm --prefix frontend run build`, then `./scripts/start-all.ps1 -SuppressSystemAlerts`. ngrok uses the new control header and the probe path `/webhook/mwb-gateway-probe`. If push notifications are still forbidden for this deployment, disable `SCHEDULER_NOTIFY_ENABLED` and `RECEIVE_HEALTH_ALERTS_ENABLED` through the process environment, and keep paid jobs within what is authorized this time.
   - Before starting the backend, `start-all.ps1` compares `alembic current` with `alembic heads`: if the database schema is not current it stops and points back to steps 1–3; it never upgrades automatically (except for a brand-new database with no version record, where it creates the schema directly). If the services are still running, this check happens before they are stopped, so the old services are not stopped first. After steps 1–3 are done, you can also pass `-ApplyMigrations` to have the script run the step 3 upgrade for you.
   - The backend and the Webhook gateway are created as independent processes through `Win32_Process` (their parent is WMI, not inside the caller's job), so closing the launch window, ending an Agent's background shell or finishing a scheduled task does not stop the services; the caller's environment variables at that moment (including the disable settings above) are passed in full to the services. If WMI is unavailable it falls back to `Start-Process` and shows a warning.
5. **Verify**: all public-boundary cases of `node scripts/webhooks.mjs check`, `./scripts/check_runtime.ps1`, Tailscale sign-in, every place the name is displayed, Word headers, template preview and audit. Confirm that each account's `send_enabled` and `publishing.enabled` are the same before and after, and check new exports and foreign keys. Before registering a new account, set REGISTRATION_BRAND_SLUG or pass --brand.

Frontend, backend and `plugin/` are always deployed together; isolated acceptance does not mean deployed.

## Migration notes

Before a production migration, open the production database with SQLite `mode=ro`, copy it to `.runtime/` with the backup API, run upgrade／downgrade／upgrade on the copy, and check row counts per table, foreign keys and account send switches. The copy contains real content: never commit, upload or screenshot its text, and never deploy the rehearsal copy; do not use `immutable=1` to ignore a WAL that is still in use.

| Version | Notes |
|---|---|
| 0021 | Disabled providers become JSON null; an admin must verify keys in AI settings and reselect the default provider. `downgrade 0020` only restores fields that are still unset. |
| 0024 | Removes the old data-source flags from seven business tables; if any table still has true, the whole upgrade aborts and lists table names and counts, and how to handle them needs separate confirmation. |
| 0025 | Ends all old comment jobs and backfill discovery while keeping business data; downgrade does not revive old jobs, and when rolling back to old code the old automatic comment schedule must be disabled separately. |
| 0026 | Downgrading to 0025 deletes the follower snapshot table; back it up first. |
| 0027 | `downgrade 0026` removes the fallback model settings for the three providers, and AI jobs waiting for a later round are marked skipped; back up job schedules and brand AI settings before rolling back. |
| 0030 | Deletes the retired `auto_draft_jobs`; downgrade only recreates an empty table. |
| 0031 | Platform／jev credentials can be stored in the DB; when platform overrides are stored, `downgrade 0030` refuses to lose the settings, so prefer restoring the pre-upgrade backup when rolling back. |
| 0032 | Member management; existing accounts get `must_change_password=false`. |
| 0033 | Meta／Threads OAuth. |
| 0035–0043 | Publishing (0035), caption_job_json (0036, no longer used), Agent authorization (0037), Agent draft uploads (0038), deletion detection (0039), Facebook unpublished posts (0040), platform options and Threads threads (0041), stories (0042; downgrade is refused when stories exist), YouTube publishing and thumbnails (0043; downgrade is refused when YouTube publishes or thumbnails exist). Downgrading 0041 removes option／thread progress; once a thread has been sent, do not downgrade without a backup. |
| 0046 | Post thumbnail cache `post_thumbnails`. Downgrade simply drops the table (it is only a cache of platform images); after upgrading, the hourly schedule fetches them again. |
| 0048 | Instagram Reels covers: `publish_media.role` gains `cover`; existing rows are not changed. Downgrade is refused when covers exist. |
| 0049 | Facebook video／Reels covers: `publish_media.role` gains `fb_cover`; existing rows are not changed. Downgrade is refused when FB covers exist. FB covers need `pages_manage_engagement`: an existing Meta connection must be reconnected once to get it (without reconnecting, publishing still works but the cover is not applied). |

## Acceptance

**One command runs all acceptance checks**: `python scripts/verify_all.py` in the project root. It runs ruff, tsc and a build to `.runtime/verify-dist` in order, then runs in parallel pytest, the frontend tests, `scripts/*.test.mjs`, all isolated UI checks (`scripts/check_*.py` are picked up automatically, excluding `*_live.py`) and the supplementary checks (listed in `verify_all.SUPPLEMENTARY`); after all parallel steps finish it runs `runtime-clean` (`scripts/test_runtime_clean.py`) on its own, and finally scans for banned strings and hard-coded colors (a failure of `git grep` itself also counts as a failure). Each step's output is in `.runtime/verify/<step>.log`, and it only passes when the last line is `ALL PASS`. Before starting work, record the `data/` listing with `python scripts/verify_all.py snapshot-data <file>`, and compare at the end with `--data-baseline <file>`; during development use `--only pytest,check_xxx` to run only selected steps, and `--jobs 1` to run them sequentially when hunting interference; a misspelled step name raises an error that lists the available names. When `--only` does not include `build`, the UI checks use the last build in `.runtime/verify-dist` (a reminder is printed), so include `build` after changing the frontend. A new check only needs to be placed in `scripts/check_*.py` to be picked up; there is no need to record the count in docs.

UI checks use Playwright to open the locally installed Google Chrome (`runtime_tmp.py` sets `channel="chrome"`), so Chrome must be installed on the acceptance machine.

Isolation rules:

- Each check's DATABASE_PATH／EXPORT_ROOT／media and logs are pointed by `browser_harness` or `runtime_tmp` to `.runtime/tmp/<unique name>/`; pure CSS checks and helpers do not open a database. Checks do not read production settings or credentials, do not call real AI or platforms, and do not connect to the outside (platforms are always HTTP mocks).
- Do not overwrite the `frontend/dist` that is being served: build into `.runtime/` and point `FRONTEND_DIST_DIR` at it.

  ```powershell
  npm --prefix frontend run build -- --outDir ../.runtime/verification-dist
  $env:FRONTEND_DIST_DIR = (Resolve-Path .runtime/verification-dist).Path
  cd backend
  uv run python ../scripts/check_ui_scale.py
  ```

- `runtime_tmp.runtime_check` manages temporary files with `temporary_dir()`; register `cleanup()` immediately after obtaining an engine, log or subprocess, and clean up the same way on exceptions and KeyboardInterrupt; a failed deletion only prints a warning. Node builds register an after hook through `runtime_tmp.mjs`. Cleanup behavior is verified by `scripts/test_runtime_clean.py`; it checks whether `.runtime/tmp` is empty, so it must run alone after all other checks finish, and the `runtime-clean` step of `verify_all.py` is already ordered that way.
- Screenshots, Word samples and JSON reports keep only the latest run, in `.runtime/check-output/<entry script name>/`, which is cleared at the start of each run; before／after comparisons across runs must be saved elsewhere.
- Acceptance scripts only stop the isolated processes they created themselves. `*_live.py` is outside acceptance and requires separate explicit authorization to run.
- Contrast checks read CSS only: text ≥4.5:1, icons／focus／charts ≥3:1.
- `eval_jev_questions.py` by default runs only an offline transport stand-in; passing verifies the pipeline only, not model quality. `--live` and `evaluate_jev_hard.py` call a paid API and must be specified explicitly.

Stability of parallel acceptance: the default `--jobs 4` makes pytest and browser checks compete for CPU, so checks must not depend on being "fast enough when run alone".

1. The query count and no-write assertions of `test_dashboard_trends_scale_read_only` are structural assertions; the time threshold only compares the best of five consecutive runs after warm-up.
2. The database steps of upload endpoints always run in a threadpool: waiting for the SQLite write lock on the event loop freezes the server, producing a deadlock of about 15 seconds followed by a 503 (`test_upload_waits_for_write_lock_off_event_loop` reproduces it reliably). Media upload／removal and saving on the publish page share the same queue.
3. When a draft is opened and its content is unchanged, the automatic check only calls `/check` without saving, to avoid needlessly incrementing version and causing conflicts with the Agent's `prepare_publish`.
4. Isolated check servers disable idle connection closing with `ports.KEEP_ALIVE_SECONDS`, to avoid `socket hang up` when Playwright reuses connections; new checks that start uvicorn must use this setting too.

## Backend tests

Run in `backend/`. Parallel mode is for everyday acceptance; single-threaded mode is for debugging and measurement:

```powershell
uv run pytest -q -n auto --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
uv run pytest -q --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
```

- Each test session (each worker when parallel) runs `alembic upgrade head` only once to create a template database, and each test copies it to its own `tmp_path` with the SQLite backup API. The template is bound to a fingerprint of the migration contents and is not cached across runs. The implementation is in `backend/tests/migration_database.py`.
- Tests that verify migrations themselves must be marked `@pytest.mark.migration`; once marked, they run real migrations per test.
- During tests, outbound connections and DNS lookups fail immediately (only loopback is allowed); new tests must replace external calls with mocks.
- Shared helpers are in `tests/conftest.py`: `login()` (gets CSRF, signs in and returns headers for later requests) and `seed_records()` (synthetic data plus historical price rows). New tests should `from conftest import ...` directly instead of copying them.
- New tests must not depend on fixed file names, fixed ports or module-level shared state.
- When the uv／pytest cache directories are restricted, point UV_CACHE_DIR, TEMP, TMP and `--basetemp` to an isolated writable directory, without changing production data settings.

## Agent connections

The workbench provides an internal `/mcp` (Streamable HTTP) on the same port as the web app; it is reachable only from the local machine and Tailscale, and public sources keep getting 404. The interface spec is in [MCP規範](mcp-spec.md) (MCP spec). Members first join Tailscale, then open **Settings → My account → Install Agent** using the internal HTTPS URL; no access to the private GitHub repo is needed. localhost downloads are only for reference and testing; archives for a Claude-hosted marketplace must use HTTPS.

**Claude Code** (at least v2.1.224):

```text
/plugin marketplace add <內部網址>/plugin/marketplace.json
/plugin install mwb@marketing-workbench
```

(`<內部網址>` is the internal URL.)

Go to `/plugin → Marketplaces`, choose marketing-workbench and turn on Enable auto-update (members must do this themselves); the first time the MCP is used, sign in with your own workbench account and approve. Update manually with `/plugin marketplace update marketing-workbench`, then start a new conversation. Users can also load the development files themselves from the repo root with `claude --plugin-dir plugin/mwb`; the local URL is <http://127.0.0.1:8000/mcp>.

**Codex** (skills + config): switch the install section to Codex, download and unzip, put the five folders under skills into `~/.agents/skills/` (back up existing content with the same names first), merge the ZIP's config.toml into `~/.codex/config.toml`, then run `codex mcp login mwb` to approve with your own account. Read-only tools use approval_mode=approve; all writes and confirm_publish use prompt. Client-side approval settings do not replace backend permissions or publish confirmation. To update, download again and merge. Why this approach: the installed server policy of a Codex plugin must be set by the user in config, and `codex plugin marketplace add` does not accept a hosted JSON URL.

**Claude desktop**: switch to Claude desktop and download the `.mcpb`, then in the desktop app choose that file under "Settings → Extensions → Install Extension". Copy the workbench URL from the install section (locally you can enter <http://127.0.0.1:8000>), create a connection token under **Agent connections** and paste it into the extension settings. To update, download the new version and reinstall; removing the extension does not revoke access in the workbench. Verification of the official format and the manual mcpb verification commands are in `plugin/README.md`.

**Hermes**: see "Hermes connection" in [MCP規範](mcp-spec.md).

**Publishing a new plugin version**: change `plugin/mwb/` → bump the version in `.claude-plugin/plugin.json` and sync the development `.mcp.json` header → run `uv run python ../scripts/update_plugin_hash.py` in backend → run tests → an authorized operator deploys frontend, backend and `plugin/`. plugin.json is the single source of the version; the update tool refuses to overwrite the same version with a different hash. Compatible additions do not change the MCP API version; the minimum compatible plugin is 0.3.0, and older ones can only read get_server_info／get_guide. The deployer validates the package with `claude plugin validate <解壓縮路徑>` (the unzipped path) and tries it personally before offering it to members.

**Revocation and expiry**: revoke your own OAuth／connection tokens under **My account → Agent connections**; an admin can revoke all of them after confirming on the members page. Disabling, resetting or changing a password revokes connections. Both kinds of connection expire after 30 days unused; OAuth access tokens last 1 hour and refresh tokens 30 days with rotation on every use, and reusing an old refresh token revokes the whole authorization. A schedule clears expired authorization data every hour. The audit log records the member, connection name and authorization id, never secrets.

## Publishing

- The publishing master switch is the Setting `publishing.enabled`, default false; only an admin can toggle it on the publish page after confirming. Deployments must not change its current value.
- Scheduled publishing and media cleanup require both SCHEDULER_ENABLED and SCHEDULER_PUBLISH_ENABLED to be on. PUBLISH_POLL_SECONDS defaults to 5 and PUBLISH_POLL_TIMEOUT to 300 seconds; unfinished Threads containers are queried again no more often than every 60 seconds. All of these have timeouts, and nothing is republished automatically.
- Media is stored in PUBLISH_MEDIA_ROOT (default `data/publish-media`). IG／Threads need the HTTPS origin of WEBHOOK_PUBLIC_URL so the platform can download `/media/<權杖>` (token); the public boundary and ngrok policy only additionally allow the exact media token path (including the `.jpg` converted for IG).
- **Check platform posts** in the publish history (`POST /api/publish/presence-check`, admins and marketers) fetches the full list again and goes through the Meta call budget; each brand can be checked manually only once per 60 seconds.
- When a result cannot be confirmed (timeout, interruption), first check on the platform whether it was published, then click **Retry failed platforms only**.
- The first real publish after a deployment must happen with the user present and with their consent at that time: Facebook first with an unpublished post, YouTube first with a **Private** video, TikTok first by sending one test video to the inbox (it does not become public unless you press publish in the app). Never press any publish button without the user's consent at that time.

**Stories**: IG Stories through the Facebook Login path need a business account plus instagram_content_publish and instagram_manage_insights. In the Meta app dashboard, check `story_insights` under Instagram Webhooks, and confirm the IG account has subscribed to the app. The receiver only writes final snapshots for story IDs already known locally, and does not store raw events.

**Read-only check of Facebook story insights** (not yet done): first get the user's consent for the account, existing unexpired stories and the read-only scope; reread the official Page Stories／insights docs, and only if the docs clearly support it, send GET requests for existing story IDs. Do not upload, create or publish. Record the version, endpoint, HTTP／error codes and whether fields are available; do not record tokens, accounts or raw responses. If the docs are still unclear, stop and keep "Facebook doesn't provide story insights".

**Platform specs to verify before deployment**: FB Reels 3–90 seconds／9:16, Threads emoji byte counting, whether published_posts covers Reels, IG Stories 3–60 seconds and JPEG specs. These values are centralized in `publish_rules.RULES`; after verifying, only that place needs changing.

## First Meta／Threads connection

Callbacks are only accepted for an admin who is signed in internally; `/api/oauth/*` on the public entry always returns 404. ACCOUNT_ENCRYPTION_KEY is provided by the deployer.

1. In Meta for Developers, under "Facebook Login → Settings", add `<內部 https 網址>/api/oauth/meta/callback` (internal HTTPS URL) to "Valid OAuth Redirect URIs" (the workbench **Setup guide** dialog shows it and lets you copy it).
2. Confirm that the use cases include `pages_manage_posts` and `instagram_content_publish`, plus `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`, `pages_manage_metadata`, `read_insights`, `instagram_basic`, `instagram_manage_comments`, `instagram_manage_insights` for reading; the retired direct-message permissions are no longer requested.
3. In the internal workbench, under **Platform connections → Meta → Manual setup (advanced)**, set the App ID and secret, then click **Connect Meta account**. If there is only one Page it is used automatically; with several Pages you must choose. FB can be connected even without IG.

Threads: under "Use cases → Threads API → Settings", get the separate App ID and secret, add `<內部 https 網址>/api/oauth/threads/callback`, confirm `threads_basic`, `threads_content_publish`, `threads_manage_replies`, `threads_manage_insights`, `threads_read_replies`, then go back to the workbench, fill in the two fields and click **Connect Threads account**. When an existing connection lacks the metrics permissions, the Threads card shows **Reconnect to get metrics and reply permissions**; until you reconnect, the post list and publishing work as usual, but insights and replies are not fetched.

state is bound to the admin and the sign-in session, and is single-use for 10 minutes. A Facebook user token with less than seven days left can only be reconnected; Page tokens have no separate expiry. Threads is checked daily and renewed only when less than seven days remain and at least 24 hours have passed since the last refresh; failure and expiry reminders go to the brand's existing LINE notification group, and if no group is set they are only recorded in the audit log.

On the first live Threads run after deployment, confirm: whether the six insights can be fetched in one request (the official docs mark views and shares as in development), whether conversation accepts the limit parameter, and how often reply usernames are missing. Threads does not go through the Meta call budget or usage headers; each round is capped at 50 list pages and 300 posts of insights.

## TikTok connection

Only the TikTok for Developers Sandbox is used, with no app review (see `docs/tiktok-plan.md`). Create the app following the **Setup guide** on the TikTok card under Platform connections: in Sandbox, add Login Kit and Content Posting API (Direct Post off); for Redirect URI choose Web and enter `<BACKOFFICE_ORIGIN>/api/oauth/tiktok/callback`; Scopes are `user.info.basic`, `user.info.stats`, `video.list`, `video.upload`; add the account to connect under Target Users; required fields include public Terms of Service and Privacy Policy URLs. The Client key／Client secret are encrypted and stored from the card (`TIKTOK_*` in `.env` is only a fallback).

Connecting uses the same two-step redirect as the other platforms. The access token lasts 24 hours; when less than 5 minutes remain before a call, it is refreshed with the refresh token, and the new refresh token returned by TikTok is saved; the card shows the refresh token's expiry date. The daily OAuth maintenance refreshes in advance; if refreshing fails (`invalid_grant`), the connection is marked as needing reconnection and a LINE notification is sent once, and the same notification is sent 14 days before the refresh token expires. **Disconnect** calls TikTok revoke (if the token is already invalid it still clears normally), deletes the TikTok tokens and synced data, and keeps the account row renamed to "TikTok".

After connecting, the hourly metrics schedule reads public videos with `POST /v2/video/list/` (including view, like, comment and share counts) and writes the same list into posts and due insights snapshots; follower counts are recorded by the daily follower schedule from follower_count of `GET /v2/user/info/`. Only a non-empty list walked from the first page to the last marks missing videos as deleted (on TikTok they may have been deleted or made private) and hides them from post analytics; they are restored if they reappear. An interrupted or empty list is never used for that judgment. When the authorization needs reconnecting, the schedule simply skips TikTok without calling the API. TikTok comments are never read.

Publishing: TikTok supports videos only and sends them to the user's TikTok inbox (unaudited apps cannot post publicly directly); the inbox API does not accept a caption, so publish history provides **Copy caption**. `video.upload` is required; publish_id is saved first, a retry checks the status first, and once the video is in the inbox it is not sent again. The inbox holds at most 5 pending videos within 24 hours; beyond that it returns `inbox_full`. After sending, the publish schedule checks the status every 10 minutes (for up to 7 days), and after the user publishes in the app it shows **Published in app**. Migration 0047 relaxes the platform constraint on publish_targets; downgrade is refused if TikTok publish targets already exist.

## YouTube connection and publishing

1. Create a project in Google Cloud Console, and under "APIs & Services → Library" enable **YouTube Data API v3** and **YouTube Analytics API**.
2. Under "Google Auth Platform → Branding", create the consent screen; under "Audience" choose **External** and change the publishing status to **In production** (refresh tokens in Testing usually expire after seven days).
3. Under "Data Access", add `https://www.googleapis.com/auth/youtube.readonly` and `https://www.googleapis.com/auth/yt-analytics.readonly`; to upload videos from the publish page, also add `https://www.googleapis.com/auth/youtube.upload`.
4. Under "Clients → Create client", choose **Web application**; the authorized redirect URI must exactly match `<內部 HTTPS 網址>/api/oauth/youtube/callback` (internal HTTPS URL).
5. An admin enters the client ID／secret under **Settings → Platform connections → YouTube**, saves, and clicks **Connect YouTube account** (or **Reconnect** with "Upload videos" left checked).
6. Choose the Google account that owns the target channel; for the unverified-app warning, after confirming it is your own app, click "Advanced → Go to (app name) (unsafe)". Do not bypass organization policy. If the channel belongs to a Brand Account, choose that brand channel. Only one channel is registered at a time; with multiple brands, the channel's brand ownership must be registered first.
7. Back in the workbench, confirm the channel name and **Connected**, and on the same card set **Upload category** (default "People & Blogs"). invalid_grant marks it **Reconnect needed**; **Disconnect** revokes the authorization with Google and clears local tokens, keeping historical data.

Quota: reads are limited by the persisted `youtube.quota` to 8,000 units per US Pacific calendar day (2,000 reserved for manual operations), with at most 50 list pages and 300 posts of insights per round; `videos.insert` is counted separately in `youtube.uploads` at 100 per day; `thumbnails.set` costs about 50 units counted in `youtube.quota`. Videos longer than 15 minutes are rejected for unverified channels; the most common cause of thumbnail failure is that the channel has not passed phone verification yet, and after verifying you can click **Reapply thumbnail** (it only replaces the thumbnail without re-uploading the video; once media is cleared after 30 days it can no longer be applied). The thumbnail limit conservatively uses 2 MB for now (`RULES.youtube.thumbnail_bytes`). If Google restricts the visibility of unaudited projects, publish history shows "Actual YouTube visibility: …".

## Member management and account recovery

- An admin enters the username, display name, role and brand under **Settings → Members → Add member**. The temporary password is shown only once; hand it over securely and never paste it into the audit log, logs or documents. A new member must change the password on first sign-in.
- "**Edit** → **Reset password**" generates a new temporary password and revokes all sessions; disabling also revokes them immediately. The last active admin cannot be disabled or demoted, and admins cannot disable themselves.
- All roles change their password under **Settings → My account** (at least 12 characters, and different from the old one); on success the current session is kept and other sessions are revoked.
- Five consecutive failures on the same username lock it for 15 minutes; existing and nonexistent usernames both get "incorrect username or password".
- Other members must join the same Tailscale network; if after signing in they see **No brands assigned yet. Contact an admin.**, an admin adds the brand.
- **Forgot password?** on the sign-in page explains that members should ask an admin to reset it, and provides the admin recovery code form and the host command below. The workbench has no email or SMS channel, so the frontend offers no self-service reset that works without prior preparation.
- An admin can generate a one-time recovery code under **Settings → My account → Password recovery code** by entering the current password (shown only once; the database stores only a hash). Keep it in a password manager, not together with the password. Generating a new one invalidates the old code.
- After a successful reset with a recovery code: the new password is set, the recovery code is invalidated, all sessions and Agent connections of that account are revoked, and the sign-in lock is cleared. Only active admins can use it; any error returns "incorrect username or recovery code", and it shares the five-failure, 15-minute lock with sign-in.

If the last admin's password is forgotten and there is no recovery code, someone with operating access to the production database runs the following in an interactive terminal on the service host:

1. Confirm that the deployed version and the production `.env` point to the correct database, and create a backup following the backup procedure.
2. In `backend`, run `uv run python ../scripts/set_password.py <管理員帳號>` (admin username) and enter the new password twice at the hidden-input prompt (12–128 characters); do not put the password in command arguments or a pipe. Do not add `--create-admin` when recovering an existing admin.
3. The tool revokes all sessions of that account and clears the must-change-password flag and the sign-in lock; after signing in again, confirm the role and brand. The tool does not enable disabled accounts or change roles. `--create-admin` is a fallback for first-time initialization (normally use the web first-time setup); if the database has no brand yet it also creates the single brand (`--brand` or an interactive prompt).

## Data conversion tools

Data conversion always defaults to a read-only dry run; add `--apply` only after confirming the results. The production apply is run by the deployment operator after a backup.

### Direct-message data purge (purge_direct_messages.py)

LINE inbound messages are discarded with 200 after signature verification; LINE_CHANNEL_ACCESS_TOKEN／LINE_BOT_USER_ID and SCHEDULER_DM_ENABLED／META_DM_* are retired, and existing env values may stay but are not used. LINE notifications, NOTIFY_LINE_* and `/webhook/line-notify` are unchanged.

The deployment operator must first back up SQLite and the export folder, schedule a maintenance window with writes stopped, explicitly specify the same database／export directory, and do a dry run to check the list before applying:

```powershell
cd backend
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄>
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄> --apply
```

(`<資料庫完整路徑>` is the full database path; `<匯出根目錄>` is the export root.)

The script does not load .env or app settings; database is required and must already exist, and if export-root is not provided no files are deleted. The default read-only dry run lists counts per table, files, and raw event IDs that cannot be classified. apply uses a single BEGIN IMMEDIATE and deletes, in foreign-key order, DMs and their dependent data, all historical drafts, and contacts that appear only in DMs, keeping mixed contacts, comments, posts, ideation reports, audit_log and settings. When a mixed notification delivery contains a cached DM, that cache is deleted; public comment notifications are kept with the delivery link removed. Only pure-DM raw payloads are deleted; mixed or unknown sources are kept for a separate decision.

For exports, only the matching Markdown／Word files in DM-only contact directories and historical Word files named after DM thread IDs are deleted; ideation files are not deleted. Files whose names collide with the prefix of a kept contact are not deleted; it aborts on symbolic links or junctions. A file failure rolls back the database and restores the bytes deleted in that run; the file system and SQLite cannot jointly guarantee atomicity across a power loss, so the deployment backup cannot be skipped. The foreign-key check must be empty before and after deletion, and the audit entry `data.purge_dm` records only per-table／file counts; a rerun deletes zero and writes no audit entry. The pre-deletion backup is the source for data recovery.

### Platform data retention (data_retention.py)

Deletes data that platform terms no longer allow to be kept: on all platforms, comments older than `COMMENT_RETENTION_DAYS` (default 365) days since the workbench fetched them (counted from fetch time, not the comment's posting time) and their dependent data (classifications, notification and delivery caches, contacts no longer referenced), plus the contents of webhook raw events over the same period (only the raw text is cleared; the platform event ID is kept, so if the platform resends an old event it is treated as processed and the comment is not recreated); YouTube comments not fetched again for 30 days, and videos deleted on YouTube for more than 30 days (including metrics snapshots and thumbnails). Ideation reports only have the deleted quoted text and post descriptions removed; the ideas are kept. The user's own publish history is kept. Markdown／Word files already exported are not changed; the operator deletes them separately if needed.

The daily schedule is off by default. The deployment operator first deploys on master and runs `./scripts/backup.ps1`, then does a dry run in the **project root** to see the counts (read-only, no text printed). `--project backend` makes uv use the backend's environment; settings are always read from `.env` in the project root, regardless of the current folder:

```powershell
uv run --project backend python scripts/data_retention.py
uv run --project backend python scripts/data_retention.py --enable
```

The comments section of post analytics shows each platform's retention period from the same settings, and whether daily deletion is enabled. Add `--enable` only after confirming `would_delete`; after that it runs at most once a day, in batches of at most 500 rows each committed separately (so even a large first run does not lock the database for long), and each batch writes one `data.retention` audit entry (counts per table only).

When a commenter emails asking for deletion (the privacy policy promises handling within 7 days), back up first, then find the contact by name, preview, and delete after confirming; only that person's own comments and contact are deleted, other people's replies under them are kept, reports have that person's quoted text removed, and the audit entry `data.delete_request` records only counts:

```powershell
uv run --project backend python scripts/data_retention.py --find-commenter <名稱>
uv run --project backend python scripts/data_retention.py --delete-contact <id>
uv run --project backend python scripts/data_retention.py --delete-contact <id> --apply
```

(`<名稱>` is the commenter's name.)

YouTube **Disconnect** revokes the Google authorization and immediately deletes synced YouTube videos, snapshots, thumbnails, comments and YouTube quotes in reports; the channel account row is kept but renamed to "YouTube" (YouTube API policy requires deletion within 7 days of revocation).

Content on the Gemini free tier is used by Google to improve products and may be reviewed by humans, so the workbench does not let it process any data: while `GEMINI_PAID_TIER` is false (the default), Gemini shows as unavailable in menus, backend runs return `provider_unpaid_tier`, and scheduled reports use the brand's background provider or the first available API instead. Set it to true only after the Google Cloud project has billing linked.

### Classification fingerprint restamp (restamp_classifications.py)

The deployer backs up first, checks the historical versions, then runs `uv run python ../scripts/restamp_classifications.py --database <資料庫路徑> --shared-revision <版本> --brand-revision <版本>` (database path, version). Both versions are required; 0 means there was no prompt for that scope at the time; positive numbers are read from prompt_versions, and a missing version fails the whole run. With multiple brands, each brand looks up the same version number in its own scope, and only rows that exactly match the old fingerprint are processed. Add `--apply` only after checking total／matched／updated／unmatched; a single BEGIN IMMEDIATE transaction changes only input_hash on matching rows, writes a `classification.restamp` audit entry per row, and a rerun updates nothing. This tool does not read .env, start workers, or call platforms or models.

## Feature settings and operating notes

**AI providers and Agent writing**: text models use only official Gemini, OpenAI and Anthropic API keys; local CLIs have been removed, and any old CLI setting is treated as unset, so an admin goes to **Settings → AI → Basics**, chooses an API provider and saves. Ideation can use **Let an Agent write it**: the report stops at **Waiting for an Agent to write ideas**, then Claude Code takes over with `/mwb:ideas` and other Agents with `get_guide("ideas")`. The **Send to Claude Code**, **Open Claude chat** and **Open Codex** buttons on the report page use the official `claude://` and `codex://` links to open the desktop app with a prefilled instruction containing the report number (you still have to send it yourself); other Agents such as Antigravity use **Copy for other Agents**. If nothing is saved back within 24 hours, it fails. Recurring meeting scheduled reports always use the Gemini API. Old `mode=subscription` usage records are kept for display and not counted toward the budget.

**AI fallback and quota**: each provider's fallback model can be left empty to disable it; `AI_API_TIMEOUT_SECONDS` controls the total time for primary plus fallback (rules in "AI and message classification" in architecture). When the Gemini free-tier quota runs out, there is no retry and no switch to fallback; for continued use, set up paid billing for the project in Google AI Studio. Switching to another key or fallback model in the same project does not lift the quota.

**On-demand comment fetching**: a one-time job is created only when the user clicks **Fetch comments** on a post; `SCHEDULER_COMMENTS_ENABLED`／`COMMENTS_WAKE_ENABLED` control running and wake-up, and `META_API_CALLS_PER_HOUR` controls the shared call budget. `META_COMMENTS_AUTO_DAYS` is ignored.

**Follower counts**: the metrics schedule makes one GET per account per day. If there is no first snapshot, check `followers.errors` in the schedule results, the account registration, the official field permissions and the budget／cooldown; do not fill `fan_count` in as the follower count or substitute zero. Requires `SCHEDULER_ENABLED`, `SCHEDULER_METRICS_ENABLED` and the metrics schedule switch in the UI.

**Obsidian comment export**: the path is stored in a Setting, default `<專案根目錄>/社群留言` (project root / social comments; ignored by git), and an admin can change it to a separate folder that passes the write check; it shares EXPORT_WORKER_ENABLED with regular exports. The encrypted backup from `backup.py` includes the Obsidian documents and hashes; restored data lands in `obsidian/` at the new destination, and the deployment operator sets the path separately after checking it, without automatically overwriting existing notes. The backup destination must not overlap the comment folder.

**Platform credentials**: an admin can save platform and jev credentials in settings, taking effect immediately; the master key must be set by the deployer first, and saving is safely refused while it is unset. Removing the DB value falls back to env. `platform_credentials.py`／`platform-credentials.mjs` are local configuration bridge helpers, used only when the operator separately runs platform tools.

### Auto-start after signing in to Windows

**Start on boot** in the workspace settings is off by default, and only admins can view and toggle it; the status is queried directly from Windows Task Scheduler. Turning it on creates the root-folder task `MWB-AutoStart`: when the current Windows user signs in (AtLogOn), with a 45-second delay, Interactive, Limited, no elevation required, allowed on battery, MultipleInstances IgnoreNew, 30-minute limit. The action is `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe` with arguments `-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "<專案>\scripts\start-all.ps1"` (`<專案>` is the project), and the working directory is the project root. You must sign in to Windows first, and the network and Google Drive must be ready; notifications from the offline period are not made up. The network is often not ready right at sign-in: `tailscale.mjs check` retries every 10 seconds for up to about 2 minutes, and if it still fails it only shows a warning and the services keep running (the local URL works); the Webhook public-boundary check `webhooks.mjs check` also retries, and if it still fails, the services started this time are stopped. After a reboot, a leftover `.runtime/*.pid` that points to a process created later than the record is treated as stale and removed automatically.

Find MWB-AutoStart in the "Task Scheduler Library" to check the settings above. Turning the switch off removes the task without stopping services already running. If any setting of a task with the same name differs, both turning on and off return `autostart_conflict`; confirm its ownership manually first. After moving the project, manually check the old task and create it again. References: [New-ScheduledTaskSettingsSet](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset), [New-ScheduledTaskPrincipal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal).

### Using a different port

The backend defaults to `127.0.0.1:8000`. On the first start (no `.runtime/start-fingerprint.txt` yet) in an interactive window, if the port is taken `start-all.ps1` asks which port to use instead and writes both values below into `.env`; later starts or non-interactive runs only report an error and stop. To run two workbenches side by side on the same computer (for example a second copy to test a first-time install), in one of them change both `BACKEND_INTERNAL_URL` (for example `http://127.0.0.1:8010`) and the local URL in `APP_ORIGIN` in `.env`; if the two ports differ, `start-all.ps1` refuses to start. If Tailscale is set up, run `tailscale serve --bg --https=443 --yes <新網址>` (new URL) again (`tailscale.mjs configure` does not overwrite a proxy pointing to the old port). ngrok's 4040 admin port is still fixed, so the two copies cannot run the Webhook gateway at the same time.

## Data locations

Production data is concentrated in the project's `data/` (ignored by git): `data/db` (database), `data/export` (exports), `data/logs` (backend and MCP audit logs), `data/manual-backups` (manual pre-deployment backups), `data/legacy` (old leftovers awaiting cleanup). Local encrypted backups go in `BACKUP_LOCAL_ROOT` outside the project, with another copy in `BACKUP_DRIVE_ROOT`. The export folder must not be inside the program directory, except for subfolders of `.runtime/` and `data/` (`data/` itself is not allowed). Commands that delete ignored files, such as `git clean -x`, are forbidden.

## Backup and rollback

`backup.ps1` uses the SQLite backup API and 7-Zip AES-256; destinations are set by `BACKUP_LOCAL_ROOT`／`BACKUP_DRIVE_ROOT`, each keeping the latest 14 backups. `install-backup-task.ps1` installs the daily schedule; if a task with an old name exists, check and remove it before installing, to avoid running twice.

The backup format is `mwb-backup-v1`; restore older formats in an isolated directory with the code from the time of the backup, and never overwrite the live database directly. `backup.ps1 -Action restore -Archive <ARCHIVE> -Destination <NEW_DIRECTORY>` only accepts a destination that does not exist yet.

To roll back, first stop the services and back up the increment since the conversion, then restore into a separate directory using the automatic backup and the matching code version. Keep the new data created after the service switch; do not overwrite and lose it. Git history is not rewritten.

## Health monitoring and troubleshooting

Every five minutes the backend checks the scheduler, the public signature probe and the number of signature-verification failures, keeping 24 hours of history; outage and recovery alerts are each sent once. A whole host going offline requires external monitoring.

- Sign-in fails: check APP_ORIGIN, ALLOWED_HOSTS, the Tailscale domain and the Secure cookie.
- Messages not received: check the fixed public URL, ngrok policy, control header, signatures and backend health. Never expose the UI/API to get around the protections.
- Background jobs make no progress: check the SCHEDULER_* switches, leases, official platform rate limits and permissions; do not reset cursors to fake completion.
- Export fails: check the separate absolute path, PROTECTED_PATHS, write permissions, the encryption master key and free disk space.

### AI error codes

| Raw code | Explanation for users |
|---|---|
| provider_http_503 (Gemini) | Gemini is currently overloaded (a Google-side issue); while waiting, the automatic retry time is shown |
| provider_http_429 | Too many requests right now, or the quota has been reached |
| provider_quota_free_tier | The Gemini free-tier quota is used up; turn on a paid plan in Google AI Studio, or try again later |
| provider_rate_limited | Requests to the provider are too frequent or the quota has been reached; when a suggested wait is given, shows that you can retry in about N seconds |
| provider_quota_exhausted | Insufficient provider quota; check the provider's billing and usage limits |
| provider_time_exhausted | The model response timed out; try again later |
| provider_http_500／502／503／504 | The provider service is temporarily unavailable |
| provider_http_408／provider_timeout | The provider response timed out |
| provider_connection_error | Temporarily unable to connect to the provider |
| provider_http_401／provider_invalid_key | Invalid API key; update it in AI settings |
| provider_http_403 | Insufficient API permissions; check the key and model access |
| provider_http_402 | Insufficient API credit; check the provider's billing |
| configuration_missing／provider_unavailable | Not set up yet, or the provider is not available yet; update it in AI settings |
| provider_unpaid_tier | The Gemini free tier cannot process platform data; switch to another provider, or link billing and set `GEMINI_PAID_TIER=true` |
| monthly_budget_exceeded | This month's AI budget has been reached |
| incomplete_output／empty_output | The model did not finish／the content was refused, or no text was returned |
| input_too_large／output_too_large | Input or response too long |
| provider_failed／generation_failed | AI content generation failed; check the settings |

The error field can carry `;retry_after_seconds=N`, and the UI shows about N seconds rounded up; this is a suggested retry time, not a guarantee of availability.

### Reading database lock logs

Exceptions from `scheduler_tick_failed`, `receive_health_check_failed`, native workers, Webhooks, imports and exports all record `error_type`; SQLite busy／locked additionally has `error_code="database_locked"` and the numeric `sqlite_errorcode`. Only the class and code are recorded, never exception messages, tracebacks, SQL, parameters, third-party raw text or generated content. `DatabaseBusy` is a safe 503 after a bounded wait is exhausted; the raw SQLite class／number can be found in the `database_lock_exhausted` event of the same run.

- `sqlite_errorcode=517`: the WAL read snapshot is stale and the write upgrade fails immediately; do not just raise the busy timeout. Check whether that path ends its read transaction first and uses a write boundary before querying.
- Base codes 5 (BUSY) and 6 (LOCKED), or extended codes whose low eight bits are 5／6: lock contention. Check for long transactions, batch imports or workers running at the same time.
- `attempt` in `database_lock_retry` is 1–3; the final failure is also recorded as `database_lock_exhausted`. This is a limit of three attempts for BEGIN to acquire the lock, and the model／platform is not called again. If it keeps happening, an authorized deployer checks the versions and transaction scopes of all writers, without directly changing production data or send switches.

The 503 message is shown in the frontend error area, and you can retry once the lock is released. When an asynchronous report has already returned 202, a persistent lock may prevent even the failed status from being saved; the same process keeps it as processing, shows a temporary save error and allows a retry (up to 128 in-memory markers; after a restart it falls back to the original lease-expiry logic). Unsaved results need a manual retry.
