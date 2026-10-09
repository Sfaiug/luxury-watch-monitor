---
users: none
tests: scripts/test.sh
---
# AGENTS.md

- One process (`main_production.py`) scans watch shops every few minutes and posts each new listing to Discord. A shop is one file in `scrapers/`, one entry in `config.py` and one line in `monitor.py`'s `SCRAPER_CLASSES`.
- `scripts/test.sh` builds `.venv` from `requirements.txt` on first use and runs the suite; its arguments go to pytest, and `PYTHON` names the interpreter when `python3` is not the one to use.
- Tests never touch the network or Discord. A scraper is tested on `tests/pages/<site_key>.html`, the listing cards cut from the shop's real page with scripts and styles removed, through the `listed_watches` fixture.
- Live: `ssh live`, checkout `/home/info/luxury-watch-monitor`, service `extras-luxury-watch-monitor`, log `/home/info/logs/extras-luxury-watch-monitor.log`. A merge to `main` is live within about two minutes: `luxury-watch-monitor-deploy.timer` runs `deploy/auto_deploy.sh` there.
- Not in git, on the server only: `.env` (webhooks, bot token) and `proxies.txt` (the owner's proxies, one `host:port:user:password` per line), both in the checkout.

## Owner rules

- The owner is the only user (9 Oct 2026: "has no real users only myself").
- Alerts keep the content they have: no market price or spread, no price history, no extra fields. Asked on 9 Oct 2026 whether to build that upgrade, the owner said no.
- Every alert has the same structure whatever its source, shop, eBay or Kleinanzeigen (9 Oct 2026: "Notification structure should be the same everywhere. Should all look the same. Want consistency and ultimate simplicity").
- eBay and Kleinanzeigen arrive through filters the member makes in Discord (9 Oct 2026): a widget with a "New filter" button starts a guided flow, the member picks the store and goes through the filter questions, and at the end a channel only that member can see is created. Only watches matching that filter go to that channel.
- "The best part is no part, the best process is no process. Delete what is not truly necessary." (9 Oct 2026)
