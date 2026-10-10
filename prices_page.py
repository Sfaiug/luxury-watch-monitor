"""The owner's page of watch prices: for every reference the shops have shown, what Chrono24 offers it for
inside the EU, the worth and the most to pay worked out from that, and the owner's own buy price, set here."""

import hashlib
import hmac
import json
from datetime import datetime
from html import escape

from aiohttp import web

from agent import OPENING
from config import APP_CONFIG
from prices import Prices
from utils import parse_price
from worth import buy_limit, most_to_pay, worth

PATH = "/muv/prices"  # atlas.hopcomp.com hands /muv/ to the monitor


def key(secret: str) -> str:
    """What the page's address carries to show it is the owner's."""
    return hmac.new(secret.encode("utf-8"), b"prices", hashlib.sha256).hexdigest()[:32]


def euros(amount) -> str:
    return "–" if amount is None else f"{amount:,.0f} €".replace(",", ".")


STYLE = """
:root { color-scheme: light dark; --line: #8884; --muted: #888; --own: #2a7; }
body { font: 15px/1.4 system-ui, sans-serif; margin: 0 auto; max-width: 1100px; padding: 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 20px 0 4px; }
p { margin: 4px 0 12px; color: var(--muted); }
input[type=search] { width: 100%; box-sizing: border-box; padding: 8px; margin: 8px 0; font: inherit; }
.table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; }
th, td.n { white-space: nowrap; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
tr.own td.limit { color: var(--own); font-weight: 600; }
form { display: flex; gap: 4px; margin: 0; }
form input { width: 7em; font: inherit; padding: 2px 4px; }
"""

FILTER = """
document.querySelector('input[type=search]').addEventListener('input', e => {
  const words = e.target.value.toLowerCase().split(/\\s+/).filter(Boolean);
  for (const row of document.querySelectorAll('tbody tr'))
    row.hidden = !words.every(w => row.textContent.toLowerCase().includes(w));
});
"""


class PricesPage:
    """Shows the page to the holder of its link and takes the buy prices set on it."""

    def __init__(self, prices: Prices, secret: str, deals=None):
        self.prices = prices
        self.secret = secret
        self.deals = deals  # the buying agent's verdicts, when it runs

    def add_to(self, app: web.Application):
        app.router.add_get(PATH, self.show)
        app.router.add_post(PATH, self.set)

    def _owner(self, request: web.Request) -> bool:
        given = request.query.get("key", "")
        return bool(self.secret) and hmac.compare_digest(given, key(self.secret))

    async def show(self, request: web.Request) -> web.Response:
        if not self._owner(request):
            return web.Response(status=403, text="This page opens only from its link.")

        rows = []
        for reference, brand, model, found, searched in self.prices.references():
            value = worth(self.prices, reference)
            own = self.prices.buy_price(reference)
            market = f"{found} offers" if found is not None else "not searched yet"
            if searched:
                market += f", {searched[:10]}"
            rows.append(
                f'<tr id="{escape(reference)}" class="{"own" if own is not None else ""}">'
                f"<td>{escape(brand or '')}</td><td>{escape(model or '')}</td><td>{escape(reference)}</td>"
                f"<td>{market}</td><td class=n>{euros(value)}</td>"
                f"<td class=n>{euros(most_to_pay(value) if value is not None else None)}</td>"
                f'<td class="n limit">{euros(buy_limit(self.prices, reference))}</td>'
                f'<td><form method=post action="{PATH}?key={key(self.secret)}">'
                f'<input type=hidden name=reference value="{escape(reference)}">'
                f'<input name=price inputmode=numeric placeholder="your price" value="{"" if own is None else f"{own:.0f}"}">'
                f"<button>Set</button></form></td></tr>"
            )

        share = round(APP_CONFIG.least_profit_share * 100)
        matches = self._matches()
        html = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Watch prices</title><style>{STYLE}</style></head>
<body><h1>Watch prices</h1>
<p>Worth: the price a quarter of a watch's Chrono24 offers inside the EU ask less than, from five offers up.
Most to pay: what still leaves {share}&nbsp;% and at least {euros(APP_CONFIG.least_profit_eur)} profit after Chrono24's fee,
shipping and the margin tax. Your price, once set, is the limit in its place; an empty one gives it back.</p>
{matches}<input type=search placeholder="Find a watch: brand, model or reference">
<div class=table><table><thead><tr><th>Brand</th><th>Model</th><th>Reference</th><th>On Chrono24</th>
<th>Worth</th><th>Most to pay</th><th>Limit</th><th>Your price</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<script>{FILTER}</script></body></html>"""
        return web.Response(text=html, content_type="text/html")

    def _matches(self) -> str:
        """The buying agent's latest verdicts on Kleinanzeigen matches, newest first."""
        if not self.deals:
            return ""
        rows = []
        for verdict in self.deals.latest(50):
            reading = json.loads(verdict["reading"]) if verdict["reading"] else {}
            read = ", ".join(
                filter(None, [reading.get("reference"), (reading.get("condition") or "").replace("unknown", "").replace("_", " "),
                              "box" if reading.get("box") else "", "papers" if reading.get("papers") else ""])
            )
            rows.append(
                f'<tr class="{"own" if verdict["contact"] else ""}"><td>{verdict["judged"][:16].replace("T", " ")}</td>'
                f'<td><a href="{escape(verdict["address"])}">{escape(verdict["title"][:70])}</a></td>'
                f"<td>{escape(read)}</td><td class=n>{euros(verdict['asking'])}</td><td class=n>{euros(verdict['worth'])}</td>"
                f"<td class=n>{euros(verdict['buy_limit'])}</td><td class=\"n limit\">{euros(verdict['opening'])}</td>"
                f"<td>{escape(verdict['why'])}</td></tr>"
            )
        return (
            "<h2>Kleinanzeigen matches</h2><p>What the agent read in each match, and whether it would contact the seller,"
            f" opening at {round(OPENING * 100)}&nbsp;% of the lower of asking price and limit. Nothing is sent to sellers yet.</p>"
            "<div class=table><table><thead><tr><th>Judged</th><th>Offer</th><th>Read</th><th>Asking</th><th>Worth</th>"
            f"<th>Limit</th><th>Opening</th><th>Verdict</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
            "<h2>Watches</h2>"
        )

    async def set(self, request: web.Request) -> web.Response:
        if not self._owner(request):
            return web.Response(status=403, text="This page opens only from its link.")

        form = await request.post()
        reference = str(form.get("reference", "")).strip()
        given = str(form.get("price", "")).strip()
        price = parse_price(given) if given else None
        if not reference or (given and not price):
            return web.Response(status=400, text="A buy price is a number of euros, or nothing.")

        self.prices.set_buy_price(reference, float(price) if price else None, datetime.now())
        raise web.HTTPSeeOther(f"{PATH}?key={key(self.secret)}#{reference}")
