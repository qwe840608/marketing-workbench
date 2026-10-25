# Marketing Workbench (marketing-workbench)

A self-hosted marketing workbench for independent creators and their own brand: it collects post analytics and audience comments from Facebook, Instagram, Threads, YouTube and TikTok in one place, turns comments into content ideas, and publishes to several platforms after a two-step confirmation.

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)
![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)
![TypeScript](https://img.shields.io/badge/TypeScript-7-3178C6.svg)

[繁體中文](README_zh-TW.md) | **English** | [简体中文](README_zh-CN.md) | [日本語](README_ja.md)

> The interface is available in Traditional Chinese, Simplified Chinese, English and Japanese (screenshots show Traditional Chinese). The documentation under `docs/` is also available in all four languages.

![Dashboard](docs/images/dashboard.png)

| Post analytics | Ideation |
|---|---|
| ![Post analytics](docs/images/posts.png) | ![Ideation](docs/images/ideation.png) |

<sub>All screenshots are real screens from the author's own account, ruidefilm.</sub>

## Features

- Syncs post performance from Facebook, Instagram, Threads, YouTube and TikTok; the dashboard shows trends, growth comparisons, a conversion funnel and audience insights.
- Fetches comments on your own posts every hour; personal data is redacted before anything is sent to a cloud model.
- Gathers evidence from the comments on posts you select and produces 15 content ideas, each with your audience's own words.
- Writes scripts from an idea, checks them against your brand's banned words, and exports them.
- Publishes now or on a schedule to FB, IG, Threads and YouTube with a two-step confirmation; TikTok uploads can only go to the app's inbox as drafts.
- Built-in MCP endpoint (Streamable HTTP) for the Claude Code plugin, the Claude Desktop extension and Codex.
- Members and roles (admin, marketer, viewer), audit log, and one-time recovery codes for administrators.
- Interface in Traditional Chinese, Simplified Chinese, English and Japanese, down to a 390px phone width.
- Encrypted backups with 7-Zip and LINE notifications (brand notification groups and delivery health alerts).

Tech stack: Python 3.13, uv, FastAPI, SQLAlchemy 2, Alembic, SQLite (WAL); frontend React 19, TypeScript, Vite.

## Read before you self-host

When you host this workbench, you are the developer of your own Meta, Google and TikTok apps, and the platforms' terms apply to you.

- **Use it only for yourself or your own brand** (single brand). Do not use it to manage clients' accounts or open it to other people: that requires each platform's review, and TikTok explicitly does not accept it.
- **Account types**: Facebook needs a Page; Instagram needs a professional account linked to that Page; Threads, YouTube and TikTok work with personal accounts.
- **Write your own privacy policy and terms of service**, publish them on your own website and enter them in each platform's developer settings. Templates are in [`docs/templates/`](docs/templates/).
- **TikTok uploads arrive as inbox drafts only**; paste the caption in the TikTok app.
- **Set the Google consent screen to production**, or YouTube authorization expires every 7 days.

Details are in [`docs/compliance-notes.md`](docs/compliance-notes.md) (compliance notes), with the official source for each rule in [`docs/platform-policies.md`](docs/platform-policies.md) (platform policies).

## Installation

Requirements: Windows (the startup and backup scripts are PowerShell; macOS and Linux are not supported yet), Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js, 7-Zip and ngrok. Tailscale is recommended.

If you are not comfortable with the command line, give [`docs/agent-install-guide.md`](docs/agent-install-guide.md) (the agent install guide) to your own AI agent and let it walk you through. The guide comes in English, Traditional Chinese, Simplified Chinese and Japanese, and the agent picks the one that matches the language you use.

```powershell
# 1. Create the config file and fill in NGROK_AUTHTOKEN; data paths can stay blank (see "Environment variables")
copy .env.example .env

# 2. Backend: install dependencies, generate the encryption master key, create the database
cd backend
uv sync
uv run python ../scripts/initialize_ai_encryption.py
uv run alembic upgrade head

# 3. Frontend: build
cd ../frontend
npm ci
npm run build

# 4. Start
cd ..
./scripts/start-all.ps1
```

`start-all.ps1` creates the schema only for a brand-new database and never upgrades an existing one; see [`docs/operations.md`](docs/operations.md) for upgrades.

## Usage

On first start, if port 8000 is already taken, `start-all.ps1` asks which port to use instead and saves it to `.env`.

After starting, open http://127.0.0.1:8000 (or the port you chose) on the computer running the workbench. The first visit shows the First-time setup page: enter the administrator username, password and brand name, and you are signed in. Then, in Settings, enter each platform's app keys on its connection card and click "Connect … account". Each card's setup guide lists the callback URL to enter in the platform's developer settings.

Connect Claude Code to the workbench (copy the address from Settings → My account → Install Agent):

```text
/plugin marketplace add <internal-url>/plugin/marketplace.json
/plugin install mwb@marketing-workbench
```

Installing for Codex and Claude Desktop is described in [`docs/operations.md`](docs/operations.md#agent-connections).

### Working with an agent (MCP)

The workbench serves an MCP endpoint (Streamable HTTP) at `<internal-url>/mcp`, reachable only from the local machine and Tailscale. Besides the plugin above, any agent that supports remote MCP can connect directly: create a connection token in Settings → My account → Agent connections, put it in the `MWB_TOKEN` environment variable, and add this to the agent's MCP config (shown in Claude Code's `.mcp.json` format; other agents take the same URL and header):

```json
{
  "mcpServers": {
    "mwb": {
      "type": "http",
      "url": "<internal-url>/mcp",
      "headers": { "Authorization": "Bearer ${MWB_TOKEN}" }
    }
  }
}
```

The token is shown only once; never paste it into a chat or commit it to git. Once connected, the agent reads the server info and brand guide (including banned words) first, then fetches the full workflow with `get_guide`, so plain requests are enough:

| You can say | Tools the agent uses |
|---|---|
| “`/mwb:report` Summarize the last 30 days across platforms. Which post did best?” | `get_dashboard`, `list_posts`, `get_post` |
| “What do viewers ask most in recent comments?” | `get_popular_questions`, `list_comments` |
| “`/mwb:ideas` Come up with ideas from the comments on my last three videos.” | `start_ideation`, `get_ideation_report`, `save_ideation_ideas` |
| “`/mwb:script` Turn idea 3 into a 60-second short video script and save it once we agree.” | `get_script`, `save_script` |
| “`/mwb:post` Write Instagram and Threads captions from this script and attach this video.” | `create_draft_from_idea`, `save_publish_draft`, `create_upload_link` |
| “`/mwb:publish` Schedule it for 8 p.m. tomorrow.” | `prepare_publish`, then `confirm_publish` only after you approve |

Publishing always takes two steps: the agent shows you the platforms, accounts, full captions, media and time, and sends only after you clearly approve. Ideas and scripts are saved only after you settle on them and say to save. Slash commands are shortcuts in the Claude Code plugin; with other agents, just ask in plain words. The tools actually available are whatever the agent's tool list shows.

Deployment, updates, backups and troubleshooting are in [`docs/operations.md`](docs/operations.md); the architecture is in [`docs/architecture.md`](docs/architecture.md).

To run the backend and frontend separately during development:

```powershell
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ../frontend
npm run dev
```

## Environment variables

Copy `.env.example` to `.env`. Every backend setting has a default, and paths left blank go under `data/` in the repo; see the comments in `.env.example` for the full list.

**Must be set before starting:**

| Variable | Description |
|---|---|
| `NGROK_AUTHTOKEN` | Required when `start-all.ps1` starts the webhook gateway; it stops without it. The ngrok executable must be on PATH, or give its full path in `NGROK_PATH` |
| `ACCOUNT_ENCRYPTION_KEY` | Required before saving platform or AI keys in the UI. Run `uv run python ../scripts/initialize_ai_encryption.py` in `backend/` to write it, and back up `.env` separately; if it is lost, encrypted keys cannot be read back |

**Generated on first start, no need to fill in:** `INGEST_API_KEY`, `WEBHOOK_PROBE_SECRET`, `WEBHOOK_PUBLIC_URL` (the fixed address ngrok assigns).

**Recommended:**

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `data/db/mwb.db` | Database location; an absolute path is recommended |
| `EXPORT_ROOT` | `data/export` | Export folder |
| `LOG_PATH` | `data/logs/backend.jsonl` | Log file |
| `APP_ORIGIN` | `http://127.0.0.1:8000` | Allowed origins, comma separated. When you add an HTTPS address (for example Tailscale), `SESSION_COOKIE_SECURE` must be `true` or the app will not start |
| `BACKEND_INTERNAL_URL` | `http://127.0.0.1:8000` | Address the backend listens on. When you change the port, change the local address in `APP_ORIGIN` too, or `start-all.ps1` refuses to start; when it asks for a port it writes both |
| `ALLOWED_HOSTS` | `["127.0.0.1","localhost"]` | Allowed host names, listed one by one; wildcards are not accepted |
| `TAILSCALE_ENABLED` | `false` | Set to `true` when using Tailscale, then run `node scripts/tailscale.mjs configure` to fill in the origin and host |
| `COMMENT_RETENTION_DAYS` | `365` | Days to keep other people's comments (30–3650); a daily job deletes expired comments |

**Optional:**

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` and the matching `*_MODEL` | Built-in AI providers; administrators can also verify and store keys encrypted in the UI |
| `GEMINI_PAID_TIER` | Default `false`; set to `true` only when the Google Cloud project has billing, otherwise Gemini will not process platform data |
| `AI_MONTHLY_BUDGET_USD` | Monthly AI API budget cap |
| `NOTIFY_LINE_*` | Messaging API credentials and group for LINE notifications |
| `BACKUP_LOCAL_ROOT` / `BACKUP_DRIVE_ROOT` / `BACKUP_PASSWORD` / `SEVEN_ZIP_PATH` | Encrypted backup locations, password and 7-Zip path |

Enter each platform's app keys (Meta, Threads, YouTube, TikTok) on the platform connection cards in the UI; they are stored encrypted in the database. Tokens are written by the connection flow, so you do not fill them in. Never commit keys, tokens or passwords to git.

## Contributing

- Before sending a PR, run `uv run pytest` in `backend/`, and `npm --prefix frontend test`, `npm --prefix frontend run build` and `node --test scripts/*.test.mjs` from the repo root. The full acceptance run is `python scripts/verify_all.py` (needs Chromium).
- Tests always use isolated data and HTTP stand-ins and must never call a real platform API.
- Database changes always go through an Alembic migration.
- Wrap new interface text in `t('Traditional Chinese source text')` and add the English, Simplified Chinese and Japanese translations in `frontend/src/locales/`, following [`docs/i18n-glossary.md`](docs/i18n-glossary.md).
- Platform integrations use official APIs only; scraping, unofficial APIs and browser automation are not accepted.
- Architecture and rules: [`docs/architecture.md`](docs/architecture.md), [`docs/mcp-spec.md`](docs/mcp-spec.md), [`docs/ui-spec.md`](docs/ui-spec.md).

Pull requests are welcome. For larger changes (a new platform, database changes, permission rules), please open an issue to discuss the direction first. Response times vary; thanks for your patience.

Questions or collaboration: support@ruidefilm.com. Please report security issues by e-mail, not in a public issue.

## License

MIT License, see [`LICENSE`](LICENSE). Using this project still requires following each platform's terms; see [`docs/compliance-notes.md`](docs/compliance-notes.md).

## Acknowledgements

This project is built on many open-source projects, with special thanks to [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [Alembic](https://alembic.sqlalchemy.org/), [React](https://react.dev/), [Vite](https://vite.dev/), [uv](https://docs.astral.sh/uv/), [Playwright](https://playwright.dev/) and the [Model Context Protocol](https://modelcontextprotocol.io/).
