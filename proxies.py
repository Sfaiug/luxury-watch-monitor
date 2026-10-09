"""The way to a site: straight, or through one of the owner's proxies once the site has refused the server."""

from base64 import b64encode
from pathlib import Path
from typing import Any, Dict, List, Set

from config import APP_CONFIG

# How one proxy is named to aiohttp: its address, and its login as a header
# apart from the address, so that no error or log line that names the proxy
# carries it
Proxy = Dict[str, Any]


def load(path: str) -> List[Proxy]:
    """The proxies in a file of `host:port:user:password` (or `host:port`) lines; none without the file."""
    file = Path(path)
    if not file.exists():
        return []

    listed = []
    for line in file.read_text(encoding="utf-8").split():
        host, port, *login = line.split(":", 3)
        proxy: Proxy = {"proxy": f"http://{host}:{port}"}
        if login:
            basic = b64encode(":".join(login).encode("utf-8")).decode("ascii")
            proxy["proxy_headers"] = {"Proxy-Authorization": f"Basic {basic}"}
        listed.append(proxy)
    return listed


class Routes:
    """Remembers which sites refused a direct request; theirs go through the proxies, one after the other."""

    def __init__(self, proxies: List[Proxy]):
        self.proxies = proxies
        self._refused: Set[str] = set()
        self._turn = 0

    def way_to(self, host: str) -> Proxy:
        """What to add to a request: nothing for a direct one; for a site that has refused one, the next proxy in turn."""
        if host not in self._refused:
            return {}
        self._turn += 1
        return self.proxies[self._turn % len(self.proxies)]

    def refused(self, host: str) -> bool:
        """The site refused a request. True when that moves it from direct requests to the proxies."""
        if not self.proxies or host in self._refused:
            return False
        self._refused.add(host)
        return True


ROUTES = Routes(load(APP_CONFIG.proxies_file))
