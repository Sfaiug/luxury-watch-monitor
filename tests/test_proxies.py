"""A site that refuses the server is read through the owner's proxies."""

import asyncio
import http.server
import logging
import threading
from unittest.mock import Mock

import pytest
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import ConnectionError as CannotConnect, HTTPError, Timeout

import proxies
from utils import fetch_page

LOGIN = ("user", "secret")
ONE = {"proxy": "http://10.0.0.1:1111", "proxy_auth": LOGIN}
TWO = {"proxy": "http://10.0.0.2:2222", "proxy_auth": LOGIN}


class Web:
    """Sites that answer or refuse depending on where the request comes from; remembers each request. It is the
    session fetch_page opens for each page."""

    def __init__(self, refuses):
        self.refuses = refuses  # (host, proxy address or None) pairs that get a 403
        self.requests = []

    def __call__(self, impersonate):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, timeout=None, proxy=None, proxy_auth=None):
        host = url.split("/")[2]
        assert (proxy_auth is None) == (proxy is None)
        self.requests.append((host, proxy))
        response = Mock(status_code=403 if (host, proxy) in self.refuses else 200, text=f"page of {host}")
        response.raise_for_status = Mock(
            side_effect=HTTPError("HTTP Error 403") if response.status_code == 403 else None
        )
        return response


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    sleep = asyncio.sleep
    monkeypatch.setattr("utils.asyncio.sleep", lambda seconds: sleep(0))


def use(monkeypatch, *listed):
    monkeypatch.setattr(proxies, "ROUTES", proxies.Routes(list(listed)))


def served(monkeypatch, web):
    """The web the pages are fetched from."""
    monkeypatch.setattr("utils.AsyncSession", web)
    return web


def test_the_file_has_one_proxy_per_line_as_the_provider_lists_them(tmp_path):
    listed = tmp_path / "proxies.txt"
    listed.write_text("10.0.0.1:1111:user:se:cret\n10.0.0.2:2222\n")

    assert proxies.load(listed) == [
        # The login travels beside the address, never in it
        {"proxy": "http://10.0.0.1:1111", "proxy_auth": ("user", "se:cret")},
        {"proxy": "http://10.0.0.2:2222"},
    ]
    assert proxies.for_browser(listed) == [
        {"server": "http://10.0.0.1:1111", "username": "user", "password": "se:cret"},
        {"server": "http://10.0.0.2:2222"},
    ]
    assert proxies.load(tmp_path / "missing.txt") == []
    assert proxies.for_browser(tmp_path / "missing.txt") == []


async def test_a_refused_request_is_made_again_through_a_proxy(monkeypatch, mock_logger):
    use(monkeypatch, ONE, TWO)
    web = served(monkeypatch, Web(refuses={("tropicalwatch.com", None)}))

    assert await fetch_page("https://tropicalwatch.com/", mock_logger) == (
        "page of tropicalwatch.com"
    )
    assert web.requests == [
        ("tropicalwatch.com", None),
        ("tropicalwatch.com", "http://10.0.0.2:2222"),
    ]

    # From then on the site is asked through the proxies, each in turn
    web.requests.clear()
    await fetch_page("https://tropicalwatch.com/watches/1", mock_logger)
    await fetch_page("https://tropicalwatch.com/watches/2", mock_logger)
    assert web.requests == [
        ("tropicalwatch.com", "http://10.0.0.1:1111"),
        ("tropicalwatch.com", "http://10.0.0.2:2222"),
    ]


def dropped(monkeypatch, failure, answers_first=False):
    """Rüschenbeck as the live server meets it since 15 Oct 2026: asked directly, every try fails with failure, the
    first one after an HTTP 500 if answers_first; through a proxy it answers."""
    use(monkeypatch, ONE, TWO)
    web = served(monkeypatch, Web(refuses=set()))
    get = web.get

    async def direct(url, timeout=None, proxy=None, proxy_auth=None):
        if proxy is not None:
            return await get(url, timeout, proxy, proxy_auth)
        web.requests.append(("www.rueschenbeck.de", None))
        if answers_first and len(web.requests) == 1:
            return Mock(status_code=500, raise_for_status=Mock(side_effect=HTTPError("HTTP Error 500")))
        raise failure("Failed to perform, curl: (28) Connection timed out after 15003 milliseconds.")

    web.get = direct
    return web


@pytest.mark.parametrize("failure", [CannotConnect, Timeout])
async def test_an_unreachable_site_is_asked_through_a_proxy_from_its_next_page_on(monkeypatch, mock_logger, failure):
    web = dropped(monkeypatch, failure)

    assert await fetch_page("https://www.rueschenbeck.de/vintage-certified-pre-owned", mock_logger) is None
    assert {proxy for _, proxy in web.requests} == {None}
    web.requests.clear()
    assert await fetch_page("https://www.rueschenbeck.de/vintage-certified-pre-owned", mock_logger) == (
        "page of www.rueschenbeck.de"
    )
    assert web.requests == [("www.rueschenbeck.de", "http://10.0.0.2:2222")]


@pytest.mark.parametrize("failure", [CannotConnect, Timeout])
async def test_a_site_that_answers_one_failed_retry_stays_direct(monkeypatch, mock_logger, failure):
    web = dropped(monkeypatch, failure, answers_first=True)

    await fetch_page("https://www.rueschenbeck.de/vintage-certified-pre-owned", mock_logger)
    await fetch_page("https://www.rueschenbeck.de/vintage-certified-pre-owned", mock_logger)

    # A site that answered at one try, if with an error, is not refusing the server
    assert {proxy for _, proxy in web.requests} == {None}


async def test_a_site_that_answers_is_asked_directly(monkeypatch):
    use(monkeypatch, ONE, TWO)
    web = served(monkeypatch, Web(refuses={("tropicalwatch.com", None)}))

    await fetch_page("https://tropicalwatch.com/")
    await fetch_page("https://www.grimmeissen.de/de/uhren")

    assert web.requests[-1] == ("www.grimmeissen.de", None)


async def test_a_proxy_that_is_refused_too_gives_way_to_the_next(monkeypatch):
    use(monkeypatch, ONE, TWO)
    web = served(monkeypatch, Web(refuses={("tropicalwatch.com", None), ("tropicalwatch.com", "http://10.0.0.2:2222")}))

    assert await fetch_page("https://tropicalwatch.com/") == "page of tropicalwatch.com"
    assert web.requests == [
        ("tropicalwatch.com", None),
        ("tropicalwatch.com", "http://10.0.0.2:2222"),
        ("tropicalwatch.com", "http://10.0.0.1:1111"),
    ]


async def test_without_proxies_a_refusal_stays_a_refusal(monkeypatch, mock_logger):
    use(monkeypatch)
    web = served(monkeypatch, Web(refuses={("tropicalwatch.com", None)}))

    assert await fetch_page("https://tropicalwatch.com/", mock_logger) is None
    assert {proxy for _, proxy in web.requests} == {None}


async def test_a_proxy_that_turns_the_login_down_leaves_it_out_of_the_log(monkeypatch):
    """Against a real proxy on this machine that answers every request with 407."""

    class Refusing(http.server.BaseHTTPRequestHandler):
        def do_CONNECT(self):
            self.send_error(407)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Refusing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    use(
        monkeypatch,
        {"proxy": f"http://127.0.0.1:{server.server_address[1]}", "proxy_auth": LOGIN},
    )
    proxies.ROUTES.refused("tropicalwatch.com")
    monkeypatch.setattr("utils.AsyncSession", AsyncSession)  # the real client, through the proxy on this machine

    lines = []
    handler = logging.Handler()
    handler.emit = lambda record: lines.append(record.getMessage())
    logger = logging.getLogger("a refusing proxy")
    logger.addHandler(handler)
    logger.propagate = False

    try:
        assert await fetch_page("https://tropicalwatch.com/", logger) is None
    finally:
        server.shutdown()

    assert any("407" in line for line in lines)
    # dXNlcjpzZWNyZXQ is user:secret as Basic authentication sends it
    assert not [line for line in lines if "secret" in line or "dXNlcjpzZWNyZXQ" in line]
