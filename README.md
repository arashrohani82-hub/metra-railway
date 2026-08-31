# Métra — Offre de service bot

Private Telegram assistant for creating Métra Consultation service proposals from a client photo, email, or pasted text.

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


## Invoice generation MVP

After an accepted ODS is converted to a project, the bot can:

- prepare a 25% initial invoice, another percentage, or a fixed amount;
- show GST, QST, and total before confirmation;
- scan the OneDrive Financial folder for the next invoice number;
- generate a one-page PDF based on invoice 48;
- send from `accounting@metrastructure.ca` after explicit confirmation;
- archive the PDF in Financial and the project Correspondence folder;
- prevent a second initial invoice from the same project session.

The invoice number is separate from the project number. Example: invoice 49 for project
`P26-030-RES-...` is saved as `FAC P26-049-RES.pdf`.

Deployment refresh: invoice workflow enabled after project creation.
