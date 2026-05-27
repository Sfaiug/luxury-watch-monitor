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
DISCORD_BOT_TOKEN=...
ACTION_TOKEN_SECRET=long-random-secret
MUV_RESULT_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

`ACTION_TOKEN_SECRET` signs button custom IDs so stale or forged IDs are rejected.

## In-Discord Buttons

To make `Send to MUV` run inside Discord without opening a browser tab, watch
alerts must be sent by the Discord application bot instead of a normal incoming
webhook. The monitor can do this directly through Discord's Create Message API.

```env
DISCORD_BOT_TOKEN=...
DISCORD_ALERT_CHANNEL_ID=123456789012345678
```

You can route each monitored site to its own channel by setting site-specific
channel ids:

```env
WORLDOFTIME_CHANNEL_ID=...
GRIMMEISSEN_CHANNEL_ID=...
TROPICALWATCH_CHANNEL_ID=...
JUWELIER_EXCHANGE_CHANNEL_ID=...
WATCH_OUT_CHANNEL_ID=...
RUESCHENBECK_CHANNEL_ID=...
BACHMANN_SCHER_CHANNEL_ID=...
```

When `DISCORD_BOT_TOKEN` and a channel id are configured, the monitor sends the
watch alert with a `custom_id` button. Discord posts the click to
`DISCORD_INTERACTIONS_PATH`, and the user stays in Discord with an ephemeral
confirmation.

## Signed Link Button Fallback

If there is no Discord application public key yet, use a normal Discord link
button. The click opens a signed VM URL, and the VM queues the MUV action
server-side:

```env
ENABLE_MUV_ACTIONS=true
MUV_HTTP_ACTIONS_ENABLED=true
MUV_ACTION_BASE_URL=https://YOUR_DOMAIN
MUV_ACTION_WEB_PATH=/muv/actions
ACTION_TOKEN_SECRET=long-random-secret
```

Expose `MUV_ACTION_WEB_PATH` and `MUV_OFFER_WEBHOOK_PATH` from nginx/Caddy to the
monitor process on `DISCORD_INTERACTIONS_HOST:DISCORD_INTERACTIONS_PORT`.

## MUV Modes

Default mode is safe preparation only:

```env
MUV_SUBMISSION_MODE=prepare
MUV_AUTO_SUBMIT=false
```

In this mode a click maps the listing to MUV's model whitelist, stores the request
payload, and sends a result webhook based on the original watch alert with MUV
fields inserted.

VM-side browser submission is opt-in:

```env
MUV_SUBMISSION_MODE=browser
MUV_AUTO_SUBMIT=true
MUV_SELLER_EMAIL=...
MUV_SELLER_FIRST_NAME=...
MUV_SELLER_LAST_NAME=...
MUV_ACCEPT_TERMS=true
MUV_CONFIRM_EU_SELLER=true
MUV_DM_RESULTS_TO_REQUESTER=true
```

Then install Chromium for Playwright on the VM:

```bash
python -m playwright install chromium
```

MUV currently requires at least 3 images. Before submitting, the monitor re-checks
the original listing page for gallery images when the stored alert has too few.
It will still refuse submission unless it has enough image URLs according to
`MUV_MIN_PICTURE_COUNT`, and it only treats a browser submission as successful
when MUV returns a unique `/Sell/{request_id}?mt=...` URL.

When `MUV_DM_RESULTS_TO_REQUESTER=true`, completed MUV offer results for linked
button actions are also sent as a Discord DM to the user who clicked the button.

For personalized button submissions, configure seller profiles by Discord user
id. When profiles are configured and a requester has no matching profile, the VM
refuses submission instead of falling back to the wrong seller:

```env
MUV_SELLER_PROFILES_JSON={"256519153278517248":{"email":"seller@example.com","firstName":"Dillon","lastName":"Hoppe"}}
```

For a restricted test phase, allow only specific Discord users to submit:

```env
MUV_ALLOWED_REQUESTER_IDS=256519153278517248
```

Other users can still see the watch alerts, but their button click will not
submit to MUV while the allowlist is active.

You can keep MUV results out of shared Discord channels for linked button
actions while still DMing the requester:

```env
MUV_RESULT_DELIVERY_MODE=dm_only_for_requested
```

Without that setting, `MUV_RESULT_WEBHOOK_URL` still receives the result and the
requester also receives a DM when `MUV_DM_RESULTS_TO_REQUESTER=true`.

## Latest Notification Batch Runner

Use the guarded batch runner to re-audit recent Discord watch alerts before a
controlled batch submission:

```bash
python scripts/muv_batch_submit.py --limit 100 --audit-output /tmp/muv_batch_audit.json
```

The runner fetches the configured site channels with the bot token, extracts the
same MUV button `action_id`, stores missing action rows, maps each listing to
MUV, and reports which listings are safe to submit. It rate-limits detail-page
enrichment per host so slow sites do not get hammered.

Real submission is deliberately gated:

```bash
python scripts/muv_batch_submit.py --limit 100 --submit-ready --require-submitted 85
```

`--submit-ready` fails before any network work unless browser mode, seller
contact fields, and the two MUV consent flags are all configured. Each successful
submission must return a unique `/Sell/{request_id}?mt=...` URL.

## Offer Webhook

When an external process receives a MUV offer, it can notify the monitor and make
the monitor post the Discord result overview. For linked actions, the result
uses the original watch alert embed, including the original image, with MUV offer
fields inserted:

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
