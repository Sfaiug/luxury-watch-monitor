"""The owner's Kleinanzeigen messages, read and written the way the site's own message box does it.

Everything goes through a page of the site in a real Chrome that holds the
owner's session: the message API answers only a page of the site, with a
token the session hands out, and a first message is the offer page's own
contact form. A message counts as sent once its conversation shows it.
"""

import asyncio
from dataclasses import dataclass
from typing import Callable, List, Optional

from playwright.async_api import TimeoutError

from scrapers.kleinanzeigen import offer_url

GATEWAY = "https://gateway.kleinanzeigen.de"

# The message box's own call (bffstatic/messagebox-web, 11 Oct 2026): a token from the session, then the gateway
_CALL = """async ([method, path, body]) => {
  const token = (await fetch('/m-access-token.json', {credentials: 'include'})).headers.get('authorization');
  const headers = {Accept: 'application/json', Authorization: token, 'X-ECG-USER-AGENT': 'messagebox-1'};
  if (body !== null) headers['Content-Type'] = 'application/json';
  const answer = await fetch('%s' + path, {
    method, headers, mode: 'cors', credentials: 'include', body: body === null ? undefined : JSON.stringify(body),
  });
  const text = await answer.text();
  return {status: answer.status, data: text ? JSON.parse(text) : null};
}""" % GATEWAY
_USER = "async () => (await (await fetch('/messagebox-api/view', {credentials: 'include'})).json()).user.id"


def plain(text: str) -> str:
    """A message as both its writer and the site show it: the same words, however the lines break."""
    return " ".join(text.split())


class NotSent(Exception):
    """The site does not show the message as sent."""


class Unsent(Exception):
    """The message went nowhere: the contact form was never sent."""


@dataclass
class Message:
    outbound: bool  # written from the owner's account
    text: str
    attachments: int  # pictures sent with it
    received: str


@dataclass
class Conversation:
    id: str
    ad_id: str
    seller: str
    messages: List[Message]
    buyer: str = ""  # the account's name, as Kleinanzeigen shows it to the seller


class Messages:
    """The message box of the account whose session the page holds."""

    def __init__(self, page):
        self._page = page  # a page of the site
        self._user: Optional[int] = None

    async def _call(self, method: str, path: str, body=None):
        answer = await self._page.evaluate(_CALL, [method, path, body])
        if answer["status"] >= 400:
            raise RuntimeError(f"Kleinanzeigen answered {method} {path} with {answer['status']}")
        return answer["data"]

    async def _conversations(self) -> str:
        if self._user is None:
            self._user = await self._page.evaluate(_USER)
        return f"/messagebox/api/users/{self._user}/conversations"

    async def conversation(self, conversation_id: str) -> Conversation:
        data = await self._call("GET", f"{await self._conversations()}/{conversation_id}?contentWarnings=true")
        return Conversation(
            id=data["id"],
            ad_id=str(data["adId"]),
            seller=data.get("sellerName") or "",
            buyer=data.get("buyerName") or "",
            messages=[
                Message(
                    outbound=message["boundness"] == "OUTBOUND",
                    # The chat payload holds the whole text; the short text stands in where there is none
                    text=((message.get("unichatMessage") or {}).get("payload", {}).get("content") or {}).get("text")
                    or message.get("textShort")
                    or "",
                    attachments=len(message.get("attachments") or []),
                    received=message.get("receivedDate") or "",
                )
                for message in data.get("messages", [])
            ],
        )

    async def bought(self, ad_id: str) -> Optional[str]:
        """The conversation the account has as buyer about an offer, if it has one."""
        path, page = await self._conversations(), 0
        while True:
            data = await self._call("GET", f"{path}?page={page}&size=100")
            for listed in data.get("conversations", []):
                if str(listed["adId"]) == str(ad_id) and listed["role"] == "Buyer":
                    return listed["id"]
            if "next" not in data.get("_links", {}):
                return None
            page += 1

    async def contact(self, ad_id: str, text: str, *, before_send: Callable[[int], None] = lambda before: None) -> str:
        """Write through the offer's form; before_send records the existing message count before submission."""
        form = None
        submit = "#viewad-contact-form button.viewad-contact-submit"
        try:
            try:
                earlier = await self.bought(ad_id)
                before = len((await self.conversation(earlier)).messages) if earlier else 0
                form = await self._page.context.new_page()
                await form.add_init_script(f"""window.addEventListener('pointerdown', event => {{
                    if (event.target.closest({submit!r})) window.__watchMonitorContactPressed = true;
                }}, true);""")
                await form.goto(offer_url(ad_id), wait_until="domcontentloaded")
                await form.fill("#viewad-contact-message", text)
                await form.evaluate("window.__watchMonitorContactPressed = false")
            except Exception as e:
                raise Unsent(f"the contact form of {ad_id} was not sent: {e}") from e
            before_send(before)
            try:
                await form.click(submit)
            except TimeoutError as e:
                try:
                    # A missing marker (navigation), a crash or an unresponsive handler proves nothing.
                    untouched = await asyncio.wait_for(
                        form.evaluate("window.__watchMonitorContactPressed === false"), timeout=1,
                    )
                except Exception:
                    raise e
                if untouched:
                    raise Unsent(f"the contact form of {ad_id} could not be clicked: {e}") from e
                raise
            await form.wait_for_selector(".j-viewad-contact-success", state="visible", timeout=30_000)
            conversation_id = await self.bought(ad_id)
            if conversation_id is None:
                raise NotSent(f"no conversation about {ad_id} after contacting its seller")
            await self._shows(conversation_id, text, before)
            return conversation_id
        finally:
            if form is not None:
                await form.close()

    async def reply(self, conversation_id: str, text: str):
        before = len((await self.conversation(conversation_id)).messages)
        await self._call("POST", f"{await self._conversations()}/{conversation_id}", {"message": text})
        await self._shows(conversation_id, text, before)

    async def _shows(self, conversation_id: str, text: str, before: int):
        """Allow a few seconds for the conversation to grow beyond `before` and end with this message."""
        for attempt in range(6):
            if attempt:
                await asyncio.sleep(1)
            said = (await self.conversation(conversation_id)).messages
            if len(said) > before and said[-1].outbound and plain(said[-1].text) == plain(text):
                return
        raise NotSent(f"conversation {conversation_id} does not end with the message written")
