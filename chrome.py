"""A real Chrome on a virtual screen of its own, as Chrono24 and Kleinanzeigen let through where a headless one is
turned away (measured on the server, 10 and 11 Oct 2026)."""

import asyncio
import contextlib
import os


class Chrome:
    """One Chrome on a screen of its own, both closed with it; each window a fresh one."""

    async def __aenter__(self) -> "Chrome":
        from playwright.async_api import async_playwright

        self._open = contextlib.AsyncExitStack()
        try:
            screen = await asyncio.create_subprocess_exec(
                "Xvfb", "-displayfd", "1", "-screen", "0", "1400x900x24", "-nolisten", "tcp",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            self._open.push_async_callback(screen.wait)
            self._open.callback(screen.terminate)
            display = ":" + (await screen.stdout.readline()).decode().strip()
            playwright = await self._open.enter_async_context(async_playwright())
            self._browser = await playwright.chromium.launch(
                channel="chrome", headless=False, env={**os.environ, "DISPLAY": display}
            )
            self._open.push_async_callback(self._browser.close)
        except BaseException:
            await self._open.aclose()
            raise
        return self

    async def __aexit__(self, *exc):
        await self._open.aclose()

    async def window(self, **options):
        """A new window, German, with Playwright's context options: a proxy, a session to hold."""
        return await self._browser.new_context(locale="de-DE", **options)
