# luxury-watch-monitor

Watches seven watch shops and members' Kleinanzeigen searches, and posts each new listing to Discord. A buying agent reads promising Kleinanzeigen offers, prices them against Chrono24 and the business's own sales, and negotiates the purchase with the seller.

```bash
cp .env.example .env    # fill in the Discord webhooks and bot token
scripts/test.sh         # the test suite
python3 main_production.py
```

On the server it runs as a systemd service that updates itself from `main` (`deploy/`).
