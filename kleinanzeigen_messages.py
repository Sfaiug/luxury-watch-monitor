"""The owner's Kleinanzeigen messages, read and written the way the site's own message box does it.

Everything goes through a page of the site in a real Chrome that holds the
owner's session: the message API answers only a page of the site, with a
token the session hands out, and a first message is the offer page's own
contact form. A message counts as sent once its conversation shows it.
"""

import asyncio
import html
import json
from dataclasses import dataclass
from typing import Callable, List, Optional

from playwright.async_api import TimeoutError

from scrapers.kleinanzeigen import offer_url

GATEWAY = "https://gateway.kleinanzeigen.de"
_RESPONSE = """const response = async (answer, path) => ({status: answer.status, path, text: await answer.text()});"""
_TOKEN = """const session = await fetch('/m-access-token.json', {credentials: 'include'});
  const token = session.headers.get('authorization');
  if (!session.ok || !token) return {...await response(session, '/m-access-token.json'), error: 'no access token'};"""

# The message box's own call (bffstatic/messagebox-web, 11 Oct 2026): a token from the session, then the gateway
_CALL = """async ([method, path, body]) => {
  %s
  %s
  const headers = {Accept: 'application/json', Authorization: token, 'X-ECG-USER-AGENT': 'messagebox-1'};
  if (body !== null) headers['Content-Type'] = 'application/json';
  const answer = await fetch('%s' + path, {
    method, headers, mode: 'cors', credentials: 'include', body: body === null ? undefined : JSON.stringify(body),
  });
  return await response(answer, path);
}""" % (_RESPONSE, _TOKEN, GATEWAY)
_USER = """async () => {
  %s
  return await response(await fetch('/messagebox-api/view', {credentials: 'include'}), '/messagebox-api/view');
}""" % _RESPONSE

# The message box reads attachments[].gatewayUrl with the same authorization as its API calls.
# Read into memory only: no browser cache, local storage or file containing the picture.
_PICTURE = """async url => {
  %s
  %s
  const answer = await fetch(url, {
    headers: {Accept: 'image/*', Authorization: token}, mode: 'cors', credentials: 'include', cache: 'no-store',
  });
  if (!answer.ok) return await response(answer, 'chat picture');
  const blob = await answer.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({media_type: blob.type, data: reader.result.split(',')[1]});
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}""" % (_RESPONSE, _TOKEN)


def plain(text: str) -> str:
    """A message as its writer and the site show it, with HTML escapes and line breaks normalized."""
    return " ".join(html.unescape(text).split())


class NotSent(Exception):
    """The site does not show the message as sent."""


class Unsent(Exception):
    """The message went nowhere: the contact form was never sent."""


class CannotWrite(RuntimeError):
    """The site refuses access to a conversation."""


class LoggedOut(RuntimeError):
    """The owner's Kleinanzeigen session has ended."""


def _data(answer):
    """Keep service and session failures separate from a refused conversation."""
    status, path, text = answer["status"], answer["path"], answer["text"]
    why = f"Kleinanzeigen answered {path} with {status}: {text[:500]}"
    if answer.get("error"):
        why += f" ({answer['error']})"
    if status == 401:
        raise LoggedOut(why)
    if status == 429 or status >= 500 or answer.get("error"):
        raise RuntimeError(why)
    if status >= 400:
        if path.startswith("/messagebox/api/users/") and not text.lstrip().startswith("<"):
            raise CannotWrite(why)
        raise RuntimeError(why)
    try:
        return json.loads(text) if text else None
    except ValueError:
        raise RuntimeError(why) from None


@dataclass
class Message:
    outbound: bool  # written from the owner's account
    text: str
    attachments: List[str]  # gateway URLs, held only for this look at the conversation
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
        return _data(await self._page.evaluate(_CALL, [method, path, body]))

    async def _conversations(self) -> str:
        if self._user is None:
            self._user = _data(await self._page.evaluate(_USER))["user"]["id"]
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
                    attachments=[attachment["gatewayUrl"] for attachment in message.get("attachments") or []],
                    received=message.get("receivedDate") or "",
                )
                for message in data.get("messages", [])
            ],
        )

    async def picture(self, url: str) -> dict:
        """A chat picture, as media type and base64 data, read through the owner's session without keeping it."""
        try:
            picture = await self._page.evaluate(_PICTURE, url)
            if "status" in picture:
                _data(picture)
            if picture["media_type"] not in ("image/jpeg", "image/png", "image/gif", "image/webp") or not picture["data"]:
                raise ValueError("not a picture")
            return picture
        except LoggedOut:
            raise LoggedOut("Kleinanzeigen answered a chat picture request with 401") from None
        except Exception:
            # Neither a private attachment URL nor its contents belongs in a log.
            raise RuntimeError("Could not read a chat picture") from None

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
            earlier = await self.bought(ad_id)
            before = len((await self.conversation(earlier)).messages) if earlier else 0
            try:
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
