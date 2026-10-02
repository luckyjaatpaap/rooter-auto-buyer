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

    # ---------------------------------------------------------
    # START BROWSER
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # GET / CREATE ACCOUNT CONTEXT
    # ---------------------------------------------------------

    async def get_context(
        self,
        slot_id: str,
    ) -> BrowserContext:

        if slot_id in self.contexts:
            return self.contexts[slot_id]

        if self.browser is None:
            raise RuntimeError(
                "BrowserManager is not started"
            )

        session_dir = self.sessions.session_path(
            slot_id
        )

        storage_file = (
            session_dir / "storage_state.json"
        )

        if storage_file.exists():
            context = await self.browser.new_context(
                storage_state=str(storage_file),
                viewport={
                    "width": 1920,
                    "height": 1080,
                },
            )
        else:
            context = await self.browser.new_context(
                viewport={
                    "width": 1920,
                    "height": 1080,
                },
            )

        self.contexts[slot_id] = context

        return context

    # ---------------------------------------------------------
    # GET PAGE
    # ---------------------------------------------------------

    async def get_page(
        self,
        slot_id: str,
    ):
        context = await self.get_context(
            slot_id
        )

        pages = context.pages

        if pages:
            return pages[0]

        return await context.new_page()

    # ---------------------------------------------------------
    # LOCATION POPUP
    # ---------------------------------------------------------

    async def handle_location_popup(
        self,
        page,
    ):
        try:
            button = page.get_by_text(
                "No, stay on this site",
                exact=True,
            )

            if await button.count() > 0:
                if await button.first.is_visible():
                    await button.first.click(
                        timeout=5000
                    )

                    await page.wait_for_timeout(
                        1000
                    )

        except Exception:
            # Popup may not appear.
            # That is completely fine.
            pass

    # ---------------------------------------------------------
    # OPEN PLAYSTATION PRODUCT PAGE
    # ---------------------------------------------------------

    async def open_product_page(
        self,
        slot_id: str,
    ):
        page = await self.get_page(
            slot_id
        )

        await page.goto(
            settings.product_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await self.handle_location_popup(
            page
        )

        return page

    # ---------------------------------------------------------
    # SAVE SESSION
    # ---------------------------------------------------------

    async def save_session(
        self,
        slot_id: str,
    ):
        context = self.contexts.get(
            slot_id
        )

        if context is None:
            return

        session_dir = (
            self.sessions.session_path(
                slot_id
            )
        )

        storage_file = (
            session_dir
            / "storage_state.json"
        )

        await context.storage_state(
            path=str(storage_file)
        )

    # ---------------------------------------------------------
    # CLOSE ACCOUNT SLOT
    # ---------------------------------------------------------

    async def close_slot(
        self,
        slot_id: str,
    ):
        context = self.contexts.pop(
            slot_id,
            None,
        )

        if context is None:
            return

        await context.close()

    # ---------------------------------------------------------
    # LOGOUT / DELETE SESSION
    # ---------------------------------------------------------

    async def logout_slot(
        self,
        slot_id: str,
    ):
        await self.close_slot(
            slot_id
        )

        self.sessions.delete_session(
            slot_id
        )

    # ---------------------------------------------------------
    # CLOSE EVERYTHING
    # ---------------------------------------------------------

    async def close(self):
        for slot_id in list(
            self.contexts.keys()
        ):
            await self.close_slot(
                slot_id
            )

        if self.browser is not None:
            await self.browser.close()
            self.browser = None

        if self.playwright is not None:
            await self.playwright.stop()
            self.playwright = None
