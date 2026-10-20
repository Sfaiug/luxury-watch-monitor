---
users: none
tests: scripts/test.sh
---
# luxury-watch-monitor

One process (`main_production.py`) scans watch shops and members' Kleinanzeigen filters and posts each new listing to Discord. A filter is to end in a purchase, not in a stream of alerts: rules filter, the AI reads what passes, and where our own price data says it pays, the agent negotiates with the seller until the whole purchase stands; only then does the owner hear of it, to pay (owner rule, 10 Oct 2026). Each of the owner's decisions sits as a dated `owner rule` comment at the code it governs.

- `scripts/test.sh` builds `.venv` and runs the suite; its arguments go to pytest. Tests never touch the network or Discord: a scraper is tested on `tests/pages/<site_key>.html` through the `listed_watches` fixture.
- Live: `ssh live`, checkout `/home/info/luxury-watch-monitor`, service `extras-luxury-watch-monitor`, log `/home/info/logs/extras-luxury-watch-monitor.log`. A merge to `main` is live within about two minutes: `luxury-watch-monitor-deploy.timer` runs `deploy/auto_deploy.sh`.
- On the server only, in the checkout, never in git: `.env`, `proxies.txt`, `filters.json`, `prices.sqlite3`, `deals.sqlite3`, `kleinanzeigen_session.json` and `controlling.csv`, which names sellers.
- `scripts/simulate_negotiations.py` runs where `AGENT_MODEL` is set and the AI hub runs, and costs what the AI's messages cost.
