# MUV Discord Button Setup

This monitor can attach a `Send to MUV` Discord application button to watch alerts.
Button clicks are handled on the VM by the monitor process.

## Discord Application

1. Create a Discord application in the Discord Developer Portal.
2. Copy the application's public key into `DISCORD_PUBLIC_KEY`.
3. Expose the VM interaction endpoint over HTTPS.
4. Set the Discord Interactions Endpoint URL to:

```text
https://YOUR_DOMAIN/discord/interactions
```

The monitor listens on `DISCORD_INTERACTIONS_HOST:DISCORD_INTERACTIONS_PORT`
and expects a reverse proxy or tunnel to terminate HTTPS.

## Required Environment

```env
ENABLE_MUV_ACTIONS=true
DISCORD_INTERACTIONS_ENABLED=true
DISCORD_PUBLIC_KEY=...
ACTION_TOKEN_SECRET=long-random-secret
MUV_RESULT_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

`ACTION_TOKEN_SECRET` signs button custom IDs so stale or forged IDs are rejected.

## MUV Modes

Default mode is safe preparation only:

```env
MUV_SUBMISSION_MODE=prepare
MUV_AUTO_SUBMIT=false
```

In this mode a click maps the listing to MUV's model whitelist, stores the request
payload, and sends a result webhook with the original listing link, MUV sell link,
listing price, model match, and any missing submit requirements.

VM-side browser submission is opt-in:

```env
MUV_SUBMISSION_MODE=browser
MUV_AUTO_SUBMIT=true
MUV_SELLER_EMAIL=...
MUV_SELLER_FIRST_NAME=...
MUV_SELLER_LAST_NAME=...
MUV_ACCEPT_TERMS=true
MUV_CONFIRM_EU_SELLER=true
```

Then install Chromium for Playwright on the VM:

```bash
python -m playwright install chromium
```

MUV currently requires at least 3 images. The monitor will not attempt submission
unless the stored listing has enough image URLs according to `MUV_MIN_PICTURE_COUNT`.

## Offer Webhook

When an external process receives a MUV offer, it can notify the monitor and make
the monitor post the Discord result overview:

```http
POST /muv/offers
X-MUV-Action-Secret: ACTION_TOKEN_SECRET
Content-Type: application/json
```

```json
{
  "action_id": "stored-action-id",
  "price": "23000",
  "currency": "EUR",
  "muv_url": "https://www.meineuhrverkaufen.de/sell",
  "message": "Optional MUV note"
}
```

This keeps the monitor VM-side. The offer source can be a mailbox parser, a MUV
callback if they provide one later, or a small manual/internal relay.

You can also post a MUV offer URL directly. The monitor will fetch the MUV
review page, parse the accepted/rejected/price state, and post the result
overview:

```json
{
  "muv_url": "https://www.meineuhrverkaufen.de/Sell/REQUEST_ID?mt=MODEL_TOKEN"
}
```

## Offer Link Monitoring

To poll known MUV offer links from the 24/7 monitor process, configure:

```env
MUV_OFFER_LINK_URLS=https://www.meineuhrverkaufen.de/Sell/REQUEST_ID?mt=MODEL_TOKEN
MUV_OFFER_LINK_POLL_SECONDS=900
```

Multiple links can be comma-separated. The monitor stores the last parsed state
in `ACTION_STORE_FILE` and only sends a new Discord result webhook when the
offer state changes.
