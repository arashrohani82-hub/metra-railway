# Metra Command Center

Standalone Telegram command center for managing the Metra bot ecosystem.

## Railway deployment

Create a NEW Railway service from the existing `arashrohani82-hub/metra-railway` repository and set:

- Root Directory: `/command_center`
- Start command is provided by `Procfile`
- Generate a public domain

## Required variables

- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_TELEGRAM_USER_IDS`
- `PUBLIC_URL`
- `WEBHOOK_SECRET`
- `SETUP_SECRET`

Optional bot routing/status variables are listed in `.env.example`.

After deployment, register Telegram webhook and commands once:

`/setup?key=<SETUP_SECRET>`

## MVP capabilities

- One Telegram entry point for the Metra bot ecosystem
- Central menu for ODS, Finance, Guardian, Intelligence, Language, Website, and Inspection bots
- Per-bot open/status view
- Bots & System overview
- Initial CEO Dashboard
- `/status` health endpoint

## Next phase

- Smart natural-language router
- Direct actions across agents instead of only opening them
- Unified project, invoice, receivables, email, and KPI dashboard
- Railway/GitHub deployment health integration
