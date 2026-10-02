from typing import Dict

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from .config import settings
from .sessions import SessionManager


class BrowserManager:

    # =========================================================
    # REAL DESKTOP WINDOW — DO NOT CHANGE
    # =========================================================

    WINDOW_WIDTH = 1200
    WINDOW_HEIGHT = 675

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
                "--window-size=1200,675",
                "--force-device-scale-factor=1",
                "--disable-features=Translate",
            ],
        )

    def context_options(self):

        return {
            "viewport": None,
            "screen": {
                "width": self.WINDOW_WIDTH,
                "height": self.WINDOW_HEIGHT,
            },
            "is_mobile": False,
            "has_touch": False,
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
        }

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

        options = self.context_options()

        if storage_file.exists():

            context = await self.browser.new_context(
                storage_state=str(storage_file),
                **options,
            )

        else:

            context = await self.browser.new_context(
                **options,
            )

        self.contexts[slot_id] = context

        return context

    async def get_page(
        self,
        slot_id: str,
    ) -> Page:

        context = await self.get_context(
            slot_id
        )

        pages = context.pages

        if pages:
            return pages[0]

        return await context.new_page()

    async def handle_location_popup(
        self,
        page: Page,
    ):
        """
        Safely handles Rooter location popup.

        This function does not modify viewport, browser,
        page layout, or any other automation settings.
        """

        try:

            # Known Rooter button
            button = page.get_by_text(
                "No, stay on this site",
                exact=True,
            )

            if await button.count() > 0:

                try:

                    button = button.first

                    if await button.is_visible(
                        timeout=1500
                    ):

                        await button.click(
                            timeout=3000
                        )

                        await page.wait_for_timeout(
                            500
                        )

                        return

                except Exception:
                    pass

            # Fallback only if the exact text changed slightly
            try:

                buttons = page.locator(
                    "button"
                )

                count = await buttons.count()

                for i in range(count):

                    try:

                        current = buttons.nth(i)

                        if not await current.is_visible(
                            timeout=300
                        ):
                            continue

                        text = (
                            await current.inner_text(
                                timeout=500
                            )
                        ).strip().lower()

                        if (
                            "stay on this site"
                            in text
                        ):

                            await current.click(
                                timeout=3000
                            )

                            await page.wait_for_timeout(
                                500
                            )

                            return

                    except Exception:
                        continue

            except Exception:
                pass

        except Exception:
            # Popup handling must NEVER crash browser flow.
            pass

    async def open_product_page(
        self,
        slot_id: str,
    ) -> Page:

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

        await page.wait_for_timeout(
            2000
        )

        await page.evaluate(
            "window.scrollTo(0, 0)"
        )

        return page

    async def ensure_product_page(
        self,
        slot_id: str,
    ) -> Page:

        page = await self.get_page(
            slot_id
        )

        current_url = page.url or ""

        product_path = (
            "shop.rooter.gg/product/"
            "playstation-gift-cards"
        )

        if (
            not current_url
            or current_url == "about:blank"
            or product_path not in current_url
        ):

            page = await self.open_product_page(
                slot_id
            )

        else:

            await self.handle_location_popup(
                page
            )

            await page.evaluate(
                "window.scrollTo(0, 0)"
            )

        return page

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
            session_dir / "storage_state.json"
        )

        await context.storage_state(
            path=str(storage_file)
        )

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
