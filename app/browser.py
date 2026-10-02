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
    # FIXED DESKTOP CONFIGURATION
    # =========================================================

    VIEWPORT_WIDTH = 1536
    VIEWPORT_HEIGHT = 864

    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None

        self.contexts: Dict[str, BrowserContext] = {}

        self.sessions = SessionManager()

    # =========================================================
    # START CHROMIUM
    # =========================================================

    async def start(self):
        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-features=Translate",
                "--window-size=1536,864",
            ],
        )

    # =========================================================
    # DESKTOP CONTEXT SETTINGS
    # =========================================================

    def context_options(self):
        return {
            "viewport": {
                "width": self.VIEWPORT_WIDTH,
                "height": self.VIEWPORT_HEIGHT,
            },

            "device_scale_factor": 1,

            "is_mobile": False,

            "has_touch": False,

            "locale": "en-IN",

            "timezone_id": "Asia/Kolkata",

            "user_agent": (
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            ),
        }

    # =========================================================
    # GET / CREATE ACCOUNT CONTEXT
    # =========================================================

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

    # =========================================================
    # GET ACCOUNT PAGE
    # =========================================================

    async def get_page(
        self,
        slot_id: str,
    ) -> Page:

        context = await self.get_context(
            slot_id
        )

        pages = context.pages

        if pages:
            page = pages[0]
        else:
            page = await context.new_page()

        return page

    # =========================================================
    # HANDLE ROOTER LOCATION POPUP
    # =========================================================

    async def handle_location_popup(
        self,
        page: Page,
    ):
        try:
            button = page.get_by_text(
                "No, stay on this site",
                exact=True,
            )

            if await button.count() == 0:
                return

            button = button.first

            if await button.is_visible(
                timeout=3000
            ):
                await button.click(
                    timeout=5000
                )

                await page.wait_for_timeout(
                    1000
                )

        except Exception:
            # Popup may not appear.
            pass

    # =========================================================
    # OPEN PLAYSTATION PAGE
    # =========================================================

    async def open_product_page(
        self,
        slot_id: str,
    ) -> Page:

        page = await self.get_page(
            slot_id
        )

        await page.set_viewport_size(
            {
                "width": self.VIEWPORT_WIDTH,
                "height": self.VIEWPORT_HEIGHT,
            }
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
            1500
        )

        await page.evaluate(
            "window.scrollTo(0, 0)"
        )

        return page

    # =========================================================
    # ENSURE ACCOUNT IS ON PRODUCT PAGE
    # =========================================================

    async def ensure_product_page(
        self,
        slot_id: str,
    ) -> Page:

        page = await self.get_page(
            slot_id
        )

        await page.set_viewport_size(
            {
                "width": self.VIEWPORT_WIDTH,
                "height": self.VIEWPORT_HEIGHT,
            }
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

    # =========================================================
    # SAVE SESSION
    # =========================================================

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

    # =========================================================
    # CLOSE ONE SLOT
    # =========================================================

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

    # =========================================================
    # LOGOUT + DELETE SESSION
    # =========================================================

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

    # =========================================================
    # CLOSE EVERYTHING
    # =========================================================

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
