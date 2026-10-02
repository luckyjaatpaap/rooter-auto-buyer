from pathlib import Path
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
    # Target rendered screenshot:
    # 1536 x 864
    #
    # Website CSS viewport:
    # 1280 x 720
    #
    # Device scale factor:
    # 1.2
    #
    # 1280 * 1.2 = 1536
    # 720 * 1.2 = 864

    VIEWPORT_WIDTH = 1280
    VIEWPORT_HEIGHT = 720
    DEVICE_SCALE_FACTOR = 1.2

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
                "--disable-features=Translate",
            ],
        )

    # ---------------------------------------------------------
    # CONTEXT SETTINGS
    # ---------------------------------------------------------

    def context_options(self):
        return {
            "viewport": {
                "width": self.VIEWPORT_WIDTH,
                "height": self.VIEWPORT_HEIGHT,
            },
            "device_scale_factor": self.DEVICE_SCALE_FACTOR,
            "is_mobile": False,
            "has_touch": False,
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
        }

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

    # ---------------------------------------------------------
    # GET ACCOUNT PAGE
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # HANDLE LOCATION POPUP
    # ---------------------------------------------------------

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

            first_button = button.first

            if await first_button.is_visible(
                timeout=3000
            ):
                await first_button.click(
                    timeout=5000
                )

                await page.wait_for_timeout(
                    1000
                )

        except Exception:
            # Popup is optional.
            # If it does not appear, continue normally.
            pass

    # ---------------------------------------------------------
    # OPEN ROOTER PLAYSTATION PAGE
    # ---------------------------------------------------------

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

        # Rooter location popup handling.
        await self.handle_location_popup(
            page
        )

        # Give the page a moment to finish
        # its client-side layout.
        await page.wait_for_timeout(
            1500
        )

        # Always start from the top.
        await page.evaluate(
            "window.scrollTo(0, 0)"
        )

        return page

    # ---------------------------------------------------------
    # ENSURE PRODUCT PAGE
    # ---------------------------------------------------------

    async def ensure_product_page(
        self,
        slot_id: str,
    ) -> Page:

        page = await self.get_page(
            slot
