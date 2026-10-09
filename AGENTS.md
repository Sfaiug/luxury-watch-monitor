---
tests: scripts/test.sh
---
# AGENTS.md

- One process (`main_production.py`) scans watch shops every few minutes and posts each new listing to Discord. A shop is one file in `scrapers/`, one entry in `config.py` and one line in `monitor.py`'s `SCRAPER_CLASSES`.
- Python 3.11. `scripts/test.sh` builds `.venv` from `requirements.txt` on first use and runs the suite; its arguments go to pytest.
- Tests never touch the network or Discord.
