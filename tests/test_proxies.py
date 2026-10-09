"""A site that refuses the server is read through the owner's proxies."""

from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

import proxies
from utils import fetch_page

ONE, TWO = "http://user:secret@10.0.0.1:1111", "http://user:secret@10.0.0.2:2222"


class Web:
    """Sites that answer or refuse depending on where the request comes from; remembers each request."""

    def __init__(self, refuses):
        self.refuses = refuses  # (host, proxy or None) pairs that get a 403
        self.requests = []

    def get(self, url, headers=None, timeout=None, proxy=None):
        host = url.split("/")[2]
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
    monkeypatch.setattr("utils.asyncio.sleep", AsyncMock())


def use(monkeypatch, *addresses):
    monkeypatch.setattr(proxies, "ROUTES", proxies.Routes(list(addresses)))


def test_the_file_has_one_proxy_per_line_as_the_provider_lists_them(tmp_path):
    listed = tmp_path / "proxies.txt"
    listed.write_text("10.0.0.1:1111:user:se/cret\n10.0.0.2:2222\n")

    assert proxies.load(listed) == [
        "http://user:se%2Fcret@10.0.0.1:1111",
        "http://10.0.0.2:2222",
    ]
    assert proxies.load(tmp_path / "missing.txt") == []


async def test_a_refused_request_is_made_again_through_a_proxy(monkeypatch, mock_logger):
    use(monkeypatch, ONE, TWO)
    web = Web(refuses={("tropicalwatch.com", None)})

    assert await fetch_page(web, "https://tropicalwatch.com/", mock_logger) == (
        "page of tropicalwatch.com"
    )
    assert web.requests == [("tropicalwatch.com", None), ("tropicalwatch.com", TWO)]
    # The login is in the proxy's address and in no log line
    assert "secret" not in str(mock_logger.mock_calls)

    # From then on the site is asked through the proxies, each in turn
    web.requests.clear()
    await fetch_page(web, "https://tropicalwatch.com/watches/1", mock_logger)
    await fetch_page(web, "https://tropicalwatch.com/watches/2", mock_logger)
    assert web.requests == [("tropicalwatch.com", ONE), ("tropicalwatch.com", TWO)]


async def test_a_site_that_answers_is_asked_directly(monkeypatch):
    use(monkeypatch, ONE, TWO)
    web = Web(refuses={("tropicalwatch.com", None)})

    await fetch_page(web, "https://tropicalwatch.com/")
    await fetch_page(web, "https://www.grimmeissen.de/de/uhren")

    assert web.requests[-1] == ("www.grimmeissen.de", None)


async def test_a_proxy_that_is_refused_too_gives_way_to_the_next(monkeypatch):
    use(monkeypatch, ONE, TWO)
    web = Web(refuses={("tropicalwatch.com", None), ("tropicalwatch.com", TWO)})

    assert await fetch_page(web, "https://tropicalwatch.com/") == "page of tropicalwatch.com"
    assert web.requests == [
        ("tropicalwatch.com", None),
        ("tropicalwatch.com", TWO),
        ("tropicalwatch.com", ONE),
    ]


async def test_without_proxies_a_refusal_stays_a_refusal(monkeypatch, mock_logger):
    use(monkeypatch)
    web = Web(refuses={("tropicalwatch.com", None)})

    assert await fetch_page(web, "https://tropicalwatch.com/", mock_logger) is None
    assert {proxy for _, proxy in web.requests} == {None}
