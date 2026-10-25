# Install guide for AI agents

> **Language / 語言 / 语言 / 言語**: [繁體中文](agent安裝引導.md) | [简体中文](agent安装引导.md) | English | [日本語](エージェント向けインストールガイド.md)
>
> **Agent: before you start, work out which language the user speaks** (from the messages they write to you; if they have not written yet, from the system locale). If it is not English, read the matching version above instead and use that language with the user throughout. If none of the four matches, follow this English version but still reply in the user's language. The workbench interface can be switched to the same language too (on the sign-in page or in Settings → My account).

This document is written for an **AI agent** (such as Claude Code or Codex, an agent that can read files and run commands on the user's computer). The user hands you this document and asks you to **set up the workbench with them step by step**. The user may not be an engineer: you run the commands, check the results and explain in plain words; for steps the user must do in person, tell them exactly where to click and what to paste back.

Read [`compliance-notes.md`](compliance-notes.md) (compliance notes) before you start. This document covers only the workflow; platform rules and their official sources are in [`platform-policies.md`](platform-policies.md) (platform policies), and detailed operations are in [`operations.md`](operations.md).

UI labels below are quoted from the English interface.

## Rules for the agent (always follow)

1. **Secrets go only into the local `.env`**: never ask the user to paste keys, tokens or passwords into the chat, never print them, never write them to logs and never commit them to git. When the user needs to provide a key, have them paste it into `.env` themselves; or you may write it to the file locally without echoing the value.
2. **The user types their own passwords**: the admin password, platform sign-ins and authorization consent screens are always done by the user. Do not type or click them on the user's behalf.
3. **Never send platform content**: during setup, do not post, reply to comments or turn on any sending switch. Publishing happens only when the user clicks through the confirmation dialog in the workbench.
4. **Explain, do, then verify each step**: say in a sentence or two what you are about to do and why, check the result afterwards, and move on only when it succeeded.
5. **Ask before installing software, creating accounts or accepting anything**: for example, installing Node.js with winget or signing up for ngrok needs the user's consent first.
6. **Don't guess when the screen differs from this document**: platform consoles change. Check the official docs first, or ask the user for a screenshot, before deciding the next step.
7. **Never delete `data/`**: it holds production data. Do not run commands that delete ignored files, such as `git clean -x`.
8. **Stop if the use case doesn't fit**: if the user wants to manage clients' accounts, run brands for several different companies or open sign-up to others, explain that this is not supported and may break platform rules (see the compliance notes), and let them decide whether to continue.

## Stage 0: Confirm the use case and prepare

Ask the user these questions first; the answers decide which later steps you need:

- What is the brand name? It is created together with the admin (the workbench supports a single brand) and is used in reports, notifications and AI prompts.
- Which platforms will they manage? Facebook Page, Instagram, Threads, YouTube, TikTok; any subset is fine.
- Are these accounts **their own** (or their own brand's)?
- Do they have their own website for a privacy policy and terms of service? Every platform requires public URLs. If not, they need to set up a simple page first.
- Do they want the AI features (ideation, script writing, comment classification)? Which provider's API?
- Do they want urgent-comment notifications through LINE?

## Stage 1: Install the environment

Only **Windows** is supported for now (the startup scripts are PowerShell). Check for and install the following; skip anything already installed:

| Software | Purpose | How to check |
|---|---|---|
| Git | Download the code | `git --version` |
| uv | Manage Python 3.13 and backend packages | `uv --version` |
| Node.js (LTS) | Build the frontend, run the connection gateway | `node --version`, `npm --version` |
| 7-Zip | Encrypted backups | `C:\Program Files\7-Zip\7z.exe` exists |
| ngrok | Public entry point for platform webhooks (required to start) | `ngrok version` |
| Tailscale | Gives the workbench an internal HTTPS address; platform OAuth callbacks and other devices rely on it | `tailscale version` |

**What the user must do in person**: sign up for ngrok and copy the authtoken; sign up for and sign in to Tailscale. The user creates both accounts; you only explain the steps.

Windows may block `.ps1` scripts by default (the error mentions the execution policy). Do not change the system execution policy for the user; bypass it for a single run instead, for example `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-all.ps1`, and the same for other `.ps1` scripts.

## Stage 2: Get the code and create `.env`

1. Download the code: `git clone <repo URL>` and enter the folder.
2. Copy the config file: copy `.env.example` to `.env`.
3. Path settings (`DATABASE_PATH`, `EXPORT_ROOT`, `LOG_PATH`, `PUBLISH_MEDIA_ROOT`) **can stay blank**; they default to `data/` inside the project.
4. Have the user paste the ngrok authtoken after `NGROK_AUTHTOKEN=` in `.env`.
5. Generate the encryption master key (platform keys are stored encrypted with it). In the `backend` folder run
   ```bash
   uv run python ../scripts/initialize_ai_encryption.py
   ```
   It writes `ACCOUNT_ENCRYPTION_KEY` automatically without showing the value. Remind the user: **back up `.env` somewhere safe**; if the master key is lost, encrypted platform keys cannot be read back.
6. Backup settings (recommended): `BACKUP_LOCAL_ROOT` (a local folder), `BACKUP_DRIVE_ROOT` (for example a Google Drive for desktop folder), `BACKUP_PASSWORD` (have the user choose a long password and paste it in themselves).
7. The `*_INITIAL_PASSWORD` entries in `.env` **do not need filling**; they are only for test data.

## Stage 3: First start and creating the admin

1. Install packages and create the database (in `backend`):
   ```bash
   uv sync
   uv run alembic upgrade head
   ```
2. Check the port: run `Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue` to see whether 8000 is taken. When the user runs `start-all.ps1` in their own window, the script asks for another port on first start if 8000 is taken; but your (the agent's) shell has no interactive input, so the script just stops. If the port is taken, ask the user which port to use (for example 8010) and change both `BACKEND_INTERNAL_URL` and the local address in `APP_ORIGIN` in `.env` to that port. Replace 8000 below with it.
3. Start (back in the project root):
   ```bash
   ./scripts/start-all.ps1
   ```
   It installs frontend packages, builds the UI, and starts the backend and the webhook gateway. When you see the startup-complete message with <http://127.0.0.1:8000>, it worked.
   **Note**: the script launches the backend and webhook gateway as detached processes (`Win32_Process`), so the services keep running even after your background job or temporary shell ends. If the output warns that it could not start a detached process, it fell back to a normal start and the services may still be tied to your job; ask the user to rerun it in their own PowerShell window. After starting, poll `http://127.0.0.1:8000/api/health` to confirm. On failure, the error message names the log in `.runtime/` to read; follow it.
4. Have the user open `http://127.0.0.1:8000` in a browser on the computer running the workbench. A brand-new database shows "Create the admin": the user enters the admin username, password (12–128 characters; suggest a long passphrase not shared with other sites) and brand name, then clicks "Create and sign in". The password must not pass through you. Without a brand, connected platform accounts are not registered and the publishing and analytics pages don't work, so the brand is required. This page only works on the local address; opening it from another device or the Tailscale address shows "Finish setup on the host computer".
   Fallback if a browser isn't available: have the user run `uv run python ../scripts/set_password.py <username> --create-admin --brand "<brand name>"` in their own interactive terminal (in the `backend` folder).
5. Verify: `./scripts/check_runtime.ps1` passes everything.

## Stage 4: Set up Tailscale internal HTTPS

1. Confirm the user is signed in to Tailscale.
2. In the project root run `node scripts/tailscale.mjs configure`; it writes the internal HTTPS address to `.env`.
3. Restart: `./scripts/start-all.ps1 -Restart`.
4. Note the internal address (`https://<device>.<tailnet>.ts.net`); you need it for platform OAuth callbacks later.

## Stage 5: Privacy policy and terms of service

1. Using the templates in [`templates/`](templates/), draft both pages **from the user's actual setup**: which platforms are connected, which AI services are used, how many days `COMMENT_RETENTION_DAYS` is, and a contact email. Delete sections that don't apply; don't copy someone else's policy.
2. After the user approves the text, they publish it on their own website and get two public URLs.
3. The app name must not contain a platform name (for example, not "My TikTok Tool"); the website or brand name is a good choice.

## Stage 6: Connect platforms

First confirm the user has the right account types; if not, have them prepare them:

| Platform | Account needed |
|---|---|
| Facebook | **A Page**. The Meta API cannot read or write personal profiles; the workbench connects Pages only |
| Instagram | **A professional account** (creator or business, switchable for free in the IG app settings) **linked to the Facebook Page above**; the workbench finds the IG account through the Page, so a personal IG account can't be connected |
| Threads | A personal account is fine |
| YouTube | A Google account with a channel |
| TikTok | A personal account is fine; add it to the Sandbox Target Users |

Every platform works the same way: **the user creates an app in the platform's developer console → enters its keys in the workbench → clicks "Connect … account" in the workbench and authorizes on the platform**. If you can operate a browser, you can fill in the developer console settings by following [`agent-platform-setup-guide.md`](agent-platform-setup-guide.md) (platform setup guide for agents), within its limits: sign-ins, secrets, authorization and app review are never done for the user. Each card in Settings → Platform connections has a "Setup guide" button showing the callback URL to copy. Detailed steps are in the matching sections of [`operations.md`](operations.md).

| Platform | What the user does in the console | Key points |
|---|---|---|
| Meta (FB/IG) | Create an app in Meta for Developers, add Facebook Login, set the callback to `<internal-url>/api/oauth/meta/callback`; enter the policy URLs under basic settings | Personal use only needs standard access, no app review; whoever connects must have a role on the app |
| Threads | Add the Threads API use case to the same Meta app, callback `<internal-url>/api/oauth/threads/callback`; add their own Threads account as a tester and accept the invitation | Has its own app ID and secret |
| YouTube | In Google Cloud, create a project, enable YouTube Data API v3 and YouTube Analytics API, create a web application client, callback `<internal-url>/api/oauth/youtube/callback` | Set the consent screen publishing status to **production**, or the connection must be redone every 7 days; at the "unverified app" warning click Advanced → continue |
| TikTok | In TikTok for Developers, create an app; in Sandbox add Login Kit and Content Posting API (Direct Post off), scopes `user.info.basic`, `user.info.stats`, `video.list`, `video.upload`, callback `<internal-url>/api/oauth/tiktok/callback`, add their own account to Target Users | Videos can only go to inbox drafts (at most 5 pending in 24 hours) and the caption is pasted in the app; when posting in the app choose "Everyone", then check it is public from a signed-out browser. The Sandbox App name should be the website or brand name and must not contain TikTok. Don't submit for Production: TikTok doesn't accept personal or self-use tools |

Have the user paste keys and secrets into the workbench cards themselves (they are stored encrypted), never into the chat. After connecting, the card shows the account name and "Connected".

**Meta comment webhook (optional)**: the "Webhook" card on the platform connections page shows the ngrok public URL and the Meta comment notification URL; its "Setup guide" has the full steps. Without it, the workbench still fetches comments every hour, just more slowly.

## Stage 7: AI and notifications (optional)

- **AI service**: the admin picks a provider (Gemini, OpenAI, Anthropic) in Settings → AI → Basics, enters the API key and verifies it (stored encrypted). The Gemini API free tier uses submitted content for training, so the Google Cloud project needs billing first, then set `GEMINI_PAID_TIER` in `.env` to `true`; otherwise the workbench won't let Gemini process platform data. If the agent the user connects to the workbench signs in with a personal subscription (such as Claude Pro/Max or ChatGPT Plus), remind them to turn off training on conversations in that service's privacy settings; an agent using an API key doesn't need this.
- **jev comment classification**: jev is TypeSafe's judgment model, used for quick comment classification. On the jev card in Settings → Platform connections, follow its "Setup guide" to paste the key and click "Test connection".
- **LINE notifications**: follow the "Setup guide" on the LINE notifications card in Settings → Platform connections: create a LINE Official Account and enable the Messaging API, paste the Channel secret and Channel access token into the card, set the Webhook URL to the address the card shows (the ngrok public URL must exist first), invite the official account to a group and send a message, then in Settings → Workspace → Notifications → LINE group notifications pick the group and enable brand notifications, and finally click "Test connection". Push messages have a monthly quota.

## Stage 8: Day-to-day operations

1. **Daily backup**: `./scripts/install-backup-task.ps1` installs a daily scheduled task; run `./scripts/backup.ps1` once by hand to confirm it works.
2. **Data retention**: preview how many rows would be deleted (read only) with `uv run --project backend python scripts/data_retention.py`, confirm with the user, then add `--enable` to turn on daily deletion.
3. **Start on boot** (optional): the admin turns on "Start on boot" in Settings → Workspace.
4. **Publishing master switch**: "Turn on publishing" at the top right of the Publish page is off by default. Whether to turn it on is the user's decision and the user's click.
5. **Brand rules**: set topics, banned words and the brand prompt in Settings → Workspace → Brand template; AI and agents follow the banned words when writing. The workspace name (the product display name) is also in the workspace settings.
6. **Members** (optional): the admin adds members, assigns roles and brands in Settings → Members, and can add custom roles with the features each may use. Temporary passwords are shown only once; the user hands them over personally, not through you. Other members must join the same Tailscale network to reach the workbench.
7. **Interface language**: the sign-in page and Settings → My account switch between 繁體中文, English, 简体中文 and 日本語.

## Stage 9: Connect an agent to the workbench (optional)

The workbench provides an MCP interface so agents can help with ideas, scripts and publishing drafts. Have the user open the workbench at the **internal https address** (stage 4), go to Settings → My account → Install Agent, pick Claude Code, Codex or Claude Desktop and follow the screen; the Claude Code plugin marketplace only accepts https addresses. On first use they sign in with their own workbench account to approve. Other agents that support remote MCP can connect with a connection token; see "Working with an agent (MCP)" in the [README](../README.md). Details are in "Agent connections" in [`operations.md`](operations.md). Publishing always takes two steps: the agent prepares the details for the user to review, and sends only after the user clearly approves.

## Completion checklist

- [ ] `./scripts/check_runtime.ps1` passes and you can sign in at `http://127.0.0.1:8000`
- [ ] The brand exists (created with the admin), banned words and brand template are set
- [ ] The workbench opens at the Tailscale internal HTTPS address
- [ ] The privacy policy and terms of service are public and their URLs are entered in each platform console
- [ ] Every needed platform shows "Connected"
- [ ] The Google consent screen is in production
- [ ] The daily backup task is installed and a manual backup succeeded
- [ ] Data retention was previewed and enabled with the user's consent
- [ ] `.env` is backed up somewhere safe
- [ ] The admin generated a recovery code in Settings → My account → Password recovery code and stored it in their password manager (the agent never handles recovery codes)
- [ ] You explained to the user: the publishing master switch, TikTok drafts only, no multi-brand or managing others' accounts

## When stuck

- Startup fails: the error message names a log in `.runtime/`; read its last lines before deciding. Common causes are a taken port, a missing ngrok authtoken or missing packages. Without `NGROK_AUTHTOKEN` the script stops at the first step. If port 8000 or 4040 is taken, check which process holds it with `Get-NetTCPConnection -LocalPort 8000`; if it is another copy of the workbench, run `./scripts/stop-all.ps1` in that folder. Never kill a process you don't recognize.
- The frontend build shows a type error such as `Type 'number' is not assignable to type 'Timeout'`: usually another project left `node_modules/@types/node` in a parent folder (for example the user's home folder). The current version avoids this; if it still happens, report the error to the maintainer and don't delete the user's files.
- A platform connection fails: read the error on the card first, then compare with `operations.md` and `platform-policies.md`; mismatched permission names or callback URLs are the most common cause.
- Forgotten admin password: with a recovery code, reset it via "Forgot password?" on the sign-in page; without one, follow "Member management and account recovery" in [`operations.md`](operations.md) and run the command on the host.
