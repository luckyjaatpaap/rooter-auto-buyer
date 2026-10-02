from pathlib import Path
from typing import Dict

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)

from .config import settings
from .sessions import SessionManager


class BrowserManager:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.contexts: Dict[str, BrowserContext] = {}

        self.sessions = SessionManager()

    async def start(self):
        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

    async def get_context(self, slot_id: str) -> BrowserContext:
        if slot_id in self.contexts:
            return self.contexts[slot_id]

        if self.browser is None:
            raise RuntimeError("BrowserManager is not started")

        session_dir = self.sessions.session_path(slot_id)
        storage_file = session_dir / "storage_state.json"

        if storage_file.exists():
            context = await self.browser.new_context(
                storage_state=str(storage_file),
                viewport={"width": 1365, "height": 768},
            )
        else:
            context = await self.browser.new_context(
                viewport={"width": 1365, "height": 768},
            )

        self.contexts[slot_id] = context

        return context

    async def get_page(self, slot_id: str):
        context = await self.get_context(slot_id)

        pages = context.pages

        if pages:
            return pages[0]

        return await context.new_page()

    async def save_session(self, slot_id: str):
        context = self.contexts.get(slot_id)

        if context is None:
            return

        session_dir = self.sessions.session_path(slot_id)
        storage_file = session_dir / "storage_state.json"

        await context.storage_state(path=str(storage_file))

    async def close_slot(self, slot_id: str):
        context = self.contexts.pop(slot_id, None)

        if context is None:
            return

        await context.close()

    async def logout_slot(self, slot_id: str):
        await self.close_slot(slot_id)
        self.sessions.delete_session(slot_id)

    async def close(self):
        for slot_id in list(self.contexts.keys()):
            await self.close_slot(slot_id)

        if self.browser is not None:
            await self.browser.close()
            self.browser = None

        if self.playwright is not None:
            await self.playwright.stop()
            self.playwright = None
