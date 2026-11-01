"""Long-lived pieces shared by the workflow and the API server."""
import asyncio
from collections import defaultdict

from playwright.async_api import async_playwright

from agent.state import AgentEvent


class EventBus:
    """Keeps every event per run, and pushes new ones to live subscribers (WebSockets)."""

    def __init__(self):
        self.history = defaultdict(list)
        self.subscribers = defaultdict(set)

    async def publish(self, run_id: str, type_: str, message: str, data: dict | None = None):
        ev = AgentEvent(run_id=run_id, type=type_, message=message, data=data or {}).model_dump()
        self.history[run_id].append(ev)
        for q in list(self.subscribers[run_id]):
            q.put_nowait(ev)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue):
        self.subscribers[run_id].discard(q)


class BrowserManager:
    """One visible Chromium for the server's lifetime; one page per run, kept across pauses."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self.pages = {}

    async def start(self, headless: bool = False):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=headless, slow_mo=100)

    @property
    def browser(self):
        return self._browser

    async def page_for(self, run_id: str):
        page = self.pages.get(run_id)
        if page is None or page.is_closed():
            ctx = await self._browser.new_context(viewport={"width": 1280, "height": 900})
            page = await ctx.new_page()
            self.pages[run_id] = page
        return page

    async def close(self, run_id: str):
        page = self.pages.pop(run_id, None)
        if page is not None:
            try:
                await page.context.close()
            except Exception:
                pass

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


bus = EventBus()
browsers = BrowserManager()
