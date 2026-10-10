---
users: none
tests: scripts/test.sh
---
# AGENTS.md

- One process (`main_production.py`) scans watch shops every few minutes and posts each new listing to Discord. A shop is one file in `scrapers/`, one entry in `config.py` and one line in `monitor.py`'s `SCRAPER_CLASSES`.
- `scripts/test.sh` builds `.venv` from `requirements.txt` on first use and runs the suite; its arguments go to pytest, and `PYTHON` names the interpreter when `python3` is not the one to use.
- Tests never touch the network or Discord. A scraper is tested on `tests/pages/<site_key>.html`, the listing cards cut from the shop's real page with scripts and styles removed, through the `listed_watches` fixture.
- Live: `ssh live`, checkout `/home/info/luxury-watch-monitor`, service `extras-luxury-watch-monitor`, log `/home/info/logs/extras-luxury-watch-monitor.log`. A merge to `main` is live within about two minutes: `luxury-watch-monitor-deploy.timer` runs `deploy/auto_deploy.sh` there.
- A member's filter is one more source: a search on a marketplace (one entry in `filters.STORES`) whose matches go to a channel of its own. `filter_flow.py` is the Discord conversation that makes one, from the "New filter" button in `#new-filter`; deleting the channel ends the filter.
- `prices.Prices` remembers what every watch listed by a shop in the EU is offered for, one row per offer from its first sighting to its last: the start of the price database a watch's worth is to come from.
- `chrono24.keep_up` runs beside the scans and searches Chrono24 inside the EU for every reference in `prices.Prices`, again once a week, keeping its offers there too. Chrono24 lets only a real Chrome through, and from the server's own address not even that: each search is a page in Google Chrome (`google-chrome-stable` and `xvfb` on the server) through the next proxy in `proxies.txt`.
- Whatever calls Discord as the bot does it through `discord_api.DiscordApi.call`: alerts, the filter flow, the MUV result messages.
- Not in git, on the server only: `.env` (webhooks, bot token), `proxies.txt` (the owner's proxies, one `host:port:user:password` per line), `filters.json` (the members' filters) and `prices.sqlite3` (the offers seen), all in the checkout.

## Owner rules

- The owner is the only user (9 Oct 2026: "has no real users only myself").
- Alerts keep the content they have: no market price or spread, no price history, no extra fields. Asked on 9 Oct 2026 whether to build that upgrade, the owner said no.
- Every alert has the same structure whatever its source, shop, eBay or Kleinanzeigen (9 Oct 2026: "Notification structure should be the same everywhere. Should all look the same. Want consistency and ultimate simplicity").
- eBay and Kleinanzeigen arrive through filters the member makes in Discord (9 Oct 2026): a widget with a "New filter" button starts a guided flow, the member picks the store and goes through the filter questions, and at the end a channel only that member can see is created. Only watches matching that filter go to that channel.
- "The best part is no part, the best process is no process. Delete what is not truly necessary." (9 Oct 2026)
- A filter is to end in a purchase, not in a stream of alerts (10 Oct 2026): "the rule based system first filters out, if something goes through the AI inspects, and if potentially profitable when checked against our data, the agent will message the seller, and negotiate with him until the desired price is reached, and only then do I get a notification on discord. This way only thing I do, is set the filter, and receive notifications when payment is to be done."
- What a watch is worth comes from a price database of our own, "a large matrix of watch prices in conditions and everything, so the AI agent has a reference point", fed first by Chrono24 (10 Oct 2026: "I think chrono is the most accurate, as there is also most times a price graph").
- Prices from Chrono24 count only when the offer is from the EU (10 Oct 2026: "On chrono price comparison we need to make sure to only look at EU offers because of VAT").
- The least profit a watch must bring starts at 10% of what it is worth and at least 500 €, and the owner moves it (10 Oct 2026, to that suggestion: "Min Profit sounds good, maybe even higher. It also kind of depends on volume, its hard to quantify").
- The agent runs on the latest Haiku model at `xhigh` effort (10 Oct 2026: "For the agent I always want to use the latest haiku model in xhigh"). Which model that is today is a setting on the server, not a name in the code.

## Lessons

- A failing test is removed only when it cannot test this code: markup the scraper no longer reads, a method that does not exist. A failure that shows a defect stays as a strict xfail narrowed to the defect; one caused by the test's own setup is fixed in the test. What a removal leaves unused (fixtures, imports) goes with it. (9 Oct 2026: the pull request that repaired the suite spent three review rounds on removals that were none of these.)
- A reading defect is counted on the saved real pages before anything is built for it; a form that no real page uses stays a strict xfail. (9 Oct 2026: four pull requests and eleven review rounds went into reading "box or papers missing", which none of 19 real shop pages says.)
