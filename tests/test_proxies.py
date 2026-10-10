"""A site that refuses the server is read through the owner's proxies."""

import asyncio
import http.server
import logging
import threading
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

import proxies
from utils import fetch_page

LOGIN = {"Proxy-Authorization": "Basic dXNlcjpzZWNyZXQ="}  # user:secret
ONE = {"proxy": "http://10.0.0.1:1111", "proxy_headers": LOGIN}
TWO = {"proxy": "http://10.0.0.2:2222", "proxy_headers": LOGIN}


class Web:
    """Sites that answer or refuse depending on where the request comes from; remembers each request."""

    def __init__(self, refuses):
        self.refuses = refuses  # (host, proxy address or None) pairs that get a 403
        self.requests = []

    def get(self, url, headers=None, timeout=None, proxy=None, proxy_headers=None):
        host = url.split("/")[2]
        assert (proxy_headers is None) == (proxy is None)
        self.requests.append((host, proxy))
        response = AsyncMock()
        response.status = 403 if (host, proxy) in self.refuses else 200
        response.text.return_value = f"page of {host}"
        response.raise_for_status = Mock(
            side_effect=aiohttp.ClientResponseError(None, (), status=403)
            if response.status == 403
            else None
        )
        context = AsyncMock()
        context.__aenter__.return_value = response
        return context


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    sleep = asyncio.sleep
    monkeypatch.setattr("utils.asyncio.sleep", lambda seconds: sleep(0))


def use(monkeypatch, *listed):
    monkeypatch.setattr(proxies, "ROUTES", proxies.Routes(list(listed)))


def test_the_file_has_one_proxy_per_line_as_the_provider_lists_them(tmp_path):
    listed = tmp_path / "proxies.txt"
    listed.write_text("10.0.0.1:1111:user:se:cret\n10.0.0.2:2222\n")

    assert proxies.load(listed) == [
        # The login travels beside the address, never in it
        {
            "proxy": "http://10.0.0.1:1111",
            "proxy_headers": {"Proxy-Authorization": "Basic dXNlcjpzZTpjcmV0"},  # user:se:cret
        },
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
    web = Web(refuses={("tropicalwatch.com", None)})

    assert await fetch_page(web, "https://tropicalwatch.com/", mock_logger) == (
        "page of tropicalwatch.com"
    )
    assert web.requests == [
        ("tropicalwatch.com", None),
        ("tropicalwatch.com", "http://10.0.0.2:2222"),
    ]

    # From then on the site is asked through the proxies, each in turn
    web.requests.clear()
    await fetch_page(web, "https://tropicalwatch.com/watches/1", mock_logger)
    await fetch_page(web, "https://tropicalwatch.com/watches/2", mock_logger)
    assert web.requests == [
        ("tropicalwatch.com", "http://10.0.0.1:1111"),
        ("tropicalwatch.com", "http://10.0.0.2:2222"),
    ]


async def test_a_site_that_answers_is_asked_directly(monkeypatch):
    use(monkeypatch, ONE, TWO)
    web = Web(refuses={("tropicalwatch.com", None)})

    await fetch_page(web, "https://tropicalwatch.com/")
    await fetch_page(web, "https://www.grimmeissen.de/de/uhren")

    assert web.requests[-1] == ("www.grimmeissen.de", None)


async def test_a_proxy_that_is_refused_too_gives_way_to_the_next(monkeypatch):
    use(monkeypatch, ONE, TWO)
    web = Web(refuses={("tropicalwatch.com", None), ("tropicalwatch.com", "http://10.0.0.2:2222")})

    assert await fetch_page(web, "https://tropicalwatch.com/") == "page of tropicalwatch.com"
    assert web.requests == [
        ("tropicalwatch.com", None),
        ("tropicalwatch.com", "http://10.0.0.2:2222"),
        ("tropicalwatch.com", "http://10.0.0.1:1111"),
    ]


async def test_without_proxies_a_refusal_stays_a_refusal(monkeypatch, mock_logger):
    use(monkeypatch)
    web = Web(refuses={("tropicalwatch.com", None)})

    assert await fetch_page(web, "https://tropicalwatch.com/", mock_logger) is None
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
        {"proxy": f"http://127.0.0.1:{server.server_address[1]}", "proxy_headers": LOGIN},
    )
    proxies.ROUTES.refused("tropicalwatch.com")

    lines = []
    handler = logging.Handler()
    handler.emit = lambda record: lines.append(record.getMessage())
    logger = logging.getLogger("a refusing proxy")
    logger.addHandler(handler)
    logger.propagate = False

    try:
        async with aiohttp.ClientSession() as session:
            assert await fetch_page(session, "https://tropicalwatch.com/", logger) is None
    finally:
        server.shutdown()

    assert any("407" in line for line in lines)
    assert not [line for line in lines if "secret" in line or "dXNlcjpzZWNyZXQ" in line]
