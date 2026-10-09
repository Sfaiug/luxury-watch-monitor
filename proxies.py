"""The way to a site: straight, or through one of the owner's proxies once the site has refused the server."""

from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import quote

from config import APP_CONFIG


def load(path: str) -> List[str]:
    """Proxy addresses from a file of `host:port:user:password` (or `host:port`) lines; none without the file."""
    file = Path(path)
    if not file.exists():
        return []

    addresses = []
    for line in file.read_text(encoding="utf-8").split():
        host, port, *login = line.split(":")
        user = "".join(f"{quote(part, safe='')}:" for part in login).rstrip(":")
        addresses.append(f"http://{user + '@' if user else ''}{host}:{port}")
    return addresses


class Routes:
    """Remembers which sites refused a direct request; theirs go through the proxies, one after the other."""

    def __init__(self, proxies: List[str]):
        self.proxies = proxies
        self._refused: Set[str] = set()
        self._turn = 0

    def proxy_for(self, host: str) -> Optional[str]:
        """None for a direct request; for a site that has refused one, the next proxy in turn."""
        if host not in self._refused:
            return None
        self._turn += 1
        return self.proxies[self._turn % len(self.proxies)]

    def refused(self, host: str) -> bool:
        """The site refused a request. True when that moves it from direct requests to the proxies."""
        if not self.proxies or host in self._refused:
            return False
        self._refused.add(host)
        return True


ROUTES = Routes(load(APP_CONFIG.proxies_file))
