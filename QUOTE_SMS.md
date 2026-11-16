# Quotation email SMS notification

The Telegram quotation Send button uses `send_ods_email`. After Microsoft Graph
accepts the email (HTTP 202), it immediately calls Twilio, before OneDrive archive
and Excel synchronization. There is no polling or intentional one-minute delay.
Carrier delivery time cannot be guaranteed. An SMS problem does not resend the
email or mark the email as failed.

Configure these Railway service variables securely (never commit the token):

```
TWILIO_SMS_ENABLED=true
TWILIO_ACCOUNT_SID=<account SID>
TWILIO_AUTH_TOKEN=<existing Auth Token>
TWILIO_FROM_NUMBER=+14388129037
```

Disabled by default. The bot uses the current offer's `phone` and `odsNum`;
10-digit North American numbers are normalized to +1. Missing/invalid numbers
skip SMS and produce a Telegram notice after email sending. French and English
notices use ASCII text to stay within one SMS segment for standard ODS references.
Ensure the client expects this quotation notice.

The existing persistent `/data` volume stores `quote_sms.sqlite3`. A unique
reservation for full ODS reference + recipient prevents repeat sends across
threads, workers, and restarts sharing this volume. No automatic retries: a
timeout may already have sent the message. Inspect Twilio logs before manual
recovery. A process crash after reservation may omit the notice; it must also
be reviewed manually. Do not run replicas with separate data volumes.

Keep the Make hourly scenario inactive to avoid sending a second notification.
Before enabling production: deploy with SMS disabled, configure credentials,
test the complete Telegram email path using an internal recipient and valid
mobile, verify Twilio delivery, and confirm that the original quotation email,
OneDrive archives, and List.xlsx still succeed. Do not resend an old customer
quotation for this test. To roll back SMS alone, set `TWILIO_SMS_ENABLED=false`.
