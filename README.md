# Métra — Offre de service bot

Private Telegram assistant for creating Métra Structure service proposals from a client photo, email, or pasted text.

## Required Railway variables

- `TELEGRAM_BOT_TOKEN`
- `ANTHROPIC_API_KEY`
- `ALLOWED_TELEGRAM_USER_IDS`
- `PUBLIC_URL`
- `WEBHOOK_SECRET`
- `SETUP_SECRET`
- `DATA_DIR=/data`

Attach a Railway volume at `/data` before deploying. After deployment, register the webhook and Telegram commands once through:

`/setup?key=<SETUP_SECRET>`

Never commit real tokens or secret values.
