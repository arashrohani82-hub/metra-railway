# Metra — Offre de service bot

Private Telegram assistant for creating Metra Consultation service proposals from a client photo, email, or pasted text.

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

## English service proposals (QC / ON / BC)

Start with `/start` or `/new`, select **English** or **Français**, then select
the project province and the STR/CIV/GEO department. The same confirmed scope,
fees, payment terms, selected conditions and exclusions are used in each
language. English mode covers Telegram questions/buttons, PDF, editable Excel,
proposal email preview/outgoing email and confirmed proposal follow-up emails.

Language/province are saved in draft and offer history and restored after photo
or text extraction. Numbering, callback identifiers and OneDrive paths remain
unchanged. Background jobs retain the current language. Standard translations
are bundled in `english_standard_text.json`; dynamic text is translated using
the existing Anthropic client, batched and cached on the persistent volume.
Translation failures or altered numbers/references stop document generation.
No additional API credential is required. The source draft is not rewritten by
document translation, and email still requires the existing send confirmation.

Province selection identifies the project; it does not certify individual or
firm registration, choose a tax rate, or modify the existing invoice engine.
The English proposal states whether taxes are extra or included, as confirmed
in the source workflow. Verify Ontario PEO licensing/Certificate of Authorization
and BC EGBC registration/Permit to Practice before offering regulated services.

Validation: `ANTHROPIC_API_KEY=test-local-only DATA_DIR=/tmp/metra-tests python -m unittest test_proposal_language test_civil_exclusions test_technical_content test_security`.
Provider and Telegram I/O are mocked in the language integration tests; no
customer email is sent and no production draft is edited during tests.


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

## Household shopping bot

The same Railway web process can host a separate, private Telegram bot for
household shopping and consumption tracking. It is inactive unless
`HOUSEHOLD_BOT_TOKEN` is set. Configure these Railway variables:

- `HOUSEHOLD_BOT_TOKEN`
- `HOUSEHOLD_WEBHOOK_SECRET`
- `HOUSEHOLD_SETUP_SECRET` (falls back to `SETUP_SECRET`)
- `HOUSEHOLD_PUBLIC_URL` (falls back to `PUBLIC_URL`)
- `HOUSEHOLD_ALLOWED_TELEGRAM_USER_IDS` (falls back to the main allow-list)

The bot registers `/webhook/household` automatically after deployment and
stores its independent data at `/data/household_purchases.json`.
