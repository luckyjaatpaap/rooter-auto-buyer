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
    # REAL DESKTOP WINDOW
    # =========================================================

    WINDOW_WIDTH = 1200
    WINDOW_HEIGHT = 675

    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None

        self.contexts: Dict[str, BrowserContext] = {}

        self.sessions = SessionManager()

    # =========================================================
    # START REAL DESKTOP CHROMIUM
    # =========================================================

    async def start(self):

        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",

                # Real desktop window size
                "--window-size=1200,675",

                # Prevent Chromium from applying
                # automatic scaling.
                "--force-device-scale-factor=1",

                "--disable-features=Translate",
            ],
        )

    # =========================================================
    # DESKTOP CONTEXT
    # =========================================================

    def context_options(self):

        return {
            # IMPORTANT:
            # Do NOT use a fixed Playwright viewport.
            #
            # This lets Chromium behave like a real
            # desktop browser window.

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
            return pages[0]

        return await context.new_page()

    # =========================================================
    # LOCATION POPUP
    # =========================================================

    async def handle_location_popup(
    self,
    page: Page,
):
    """
    Smartly handles Rooter's location-detected popup.

    It tries multiple safe ways to dismiss the popup without
    changing the page layout, viewport, or other browser settings.
    """

    try:
        # Give popup a short moment to appear
        await page.wait_for_timeout(500)

        # 1. Exact known button
        selectors = [
            'text="No, stay on this site"',
            'button:has-text("No, stay on this site")',
            'text="Stay on this site"',
            'button:has-text("Stay on this site")',
        ]

        for selector in selectors:

            try:
                locator = page.locator(selector)

                count = await locator.count()

                if count == 0:
                    continue

                for i in range(count):

                    button = locator.nth(i)

                    try:
                        if await button.is_visible(
                            timeout=1000
                        ):
                            await button.click(
                                timeout=3000
                            )

                            await page.wait_for_timeout(
                                500
                            )

                            return

                    except Exception:
                        continue

            except Exception:
                continue

        # 2. If popup has an accessible button name
        try:
            button = page.get_by_role(
                "button",
                name="No, stay on this site",
                exact=True,
            )

            if await button.count() > 0:
                if await button.first.is_visible(
                    timeout=1000
                ):
                    await button.first.click(
                        timeout=3000
                    )

                    await page.wait_for_timeout(
                        500
                    )

                    return

        except Exception:
            pass

        # 3. Final smart fallback:
        # Search visible buttons containing "stay"
        try:
            buttons = page.locator("button")

            count = await buttons.count()

            for i in range(count):

                button = buttons.nth(i)

                try:
                    if not await button.is_visible(
                        timeout=500
                    ):
                        continue

                    text = (
                        await button.inner_text(
                            timeout=1000
                        )
                    ).strip().lower()

                    if (
                        "stay on this site" in text
                        or (
                            "stay" in text
                            and "site" in text
                        )
                    ):
                        await button.click(
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
        # Popup handling must never break the main flow.
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

        await page.goto(
            settings.product_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Handle:
        # "Different Location Detected"
        await self.handle_location_popup(
            page
        )

        # Give Rooter enough time to render
        # its desktop UI.
        await page.wait_for_timeout(
            2000
        )

        await page.evaluate(
            "window.scrollTo(0, 0)"
        )

        return page

    # =========================================================
    # ENSURE PLAYSTATION PAGE
    # =========================================================

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
    # CLOSE SLOT
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
    # LOGOUT
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
