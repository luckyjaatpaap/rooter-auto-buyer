import json
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

    WINDOW_WIDTH = 1200
    WINDOW_HEIGHT = 675

    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.contexts: Dict[str, BrowserContext] = {}
        self.sessions = SessionManager()

    async def start(self):
        if self.playwright is None:
            self.playwright = await async_playwright().start()

        if self.browser is None or not self.browser.is_connected():
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1200,675",
                    "--force-device-scale-factor=1",
                    "--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-default-apps",
                    "--metrics-recording-only",
                    "--mute-audio",
                    "--no-first-run",
                    "--js-flags=--max-old-space-size=512",
                ],
            )

    async def ensure_browser_alive(self):
        """Agar Chromium crash ya close ho jaye, toh turant naya browser start karega."""
        try:
            if self.browser is None or not self.browser.is_connected():
                self.contexts.clear()
                await self.start()
        except Exception:
            self.contexts.clear()
            try:
                if self.playwright:
                    await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
            self.browser = None
            await self.start()

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

    async def get_context(self, slot_id: str) -> BrowserContext:
        await self.ensure_browser_alive()

        if slot_id in self.contexts:
            ctx = self.contexts[slot_id]
            try:
                # Check if context is alive
                _ = ctx.pages
                return ctx
            except Exception:
                self.contexts.pop(slot_id, None)

        session_dir = self.sessions.session_path(slot_id)
        storage_file = session_dir / "storage_state.json"
        options = self.context_options()

        if storage_file.exists() and storage_file.stat().st_size > 10:
            try:
                context = await self.browser.new_context(
                    storage_state=str(storage_file),
                    **options,
                )
            except Exception:
                context = await self.browser.new_context(**options)
        else:
            context = await self.browser.new_context(**options)

        self.contexts[slot_id] = context
        return context

    async def get_page(self, slot_id: str) -> Page:
        context = await self.get_context(slot_id)

        try:
            valid_pages = [p for p in context.pages if not p.is_closed()]
            if valid_pages:
                # Faltu extra tabs खुले hon toh band kar do (Memory Bachao)
                for extra_page in valid_pages[1:]:
                    try:
                        await extra_page.close()
                    except Exception:
                        pass
                return valid_pages[0]
            return await context.new_page()
        except Exception:
            self.contexts.pop(slot_id, None)
            context = await self.get_context(slot_id)
            return await context.new_page()

    async def reset_slot_page(self, slot_id: str) -> Page:
        """Tab aur context ko safely close karke fresh tab banata hai (RAM Clean)."""
        try:
            ctx = self.contexts.pop(slot_id, None)
            if ctx:
                await ctx.close()
        except Exception:
            pass
        return await self.get_page(slot_id)

     # =========================================================
     # ROOTER LOCATION POPUP
     # =========================================================
     
    async def handle_location_popup(self, page: Page, slot_id: str = "SLOT") -> bool:
        try:
            await page.wait_for_timeout(600)
            
            # 1. Broad text and keyword matching for location modals
            keywords = ["no, stay on this site", "stay on this site", "stay", "dismiss", "close"]
            for kw in keywords:
                try:
                    locator = page.get_by_text(kw, exact=False)
                    count = await locator.count()
                    for i in range(count):
                        el = locator.nth(i)
                        if await el.is_visible(timeout=500):
                            await el.click(force=True, timeout=2000)
                            await page.wait_for_timeout(500)
                            return True
                except Exception:
                    pass

            # 2. Button element scanning
            buttons = page.locator("button, div[role='button'], span")
            button_count = await buttons.count()

            for index in range(button_count):
                try:
                    btn = buttons.nth(index)
                    if not await btn.is_visible(timeout=300):
                        continue

                    text = await btn.inner_text(timeout=500)
                    text = " ".join(text.split()).strip().lower()

                    if any(k in text for k in ["stay on this site", "no, stay", "dismiss"]):
                        await btn.click(force=True, timeout=2000)
                        await page.wait_for_timeout(500)
                        return True
                except Exception:
                    continue

            return False
        except Exception:
            return False

    # =========================================================
    # OPEN & ENSURE PLAYSTATION PRODUCT
    # =========================================================

    async def open_product_page(self, slot_id: str) -> Page:
        page = await self.get_page(slot_id)
        await page.goto(
            settings.product_url,
            wait_until="domcontentloaded",
            timeout=45000,
        )
        await self.handle_location_popup(page)
        await page.wait_for_timeout(1500)
        try:
            await page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        return page

    async def ensure_product_page(self, slot_id: str) -> Page:
        page = await self.get_page(slot_id)
        current_url = page.url or ""
        product_path = "shop.rooter.gg/product/playstation-gift-cards"

        if (
            not current_url
            or current_url == "about:blank"
            or product_path not in current_url
        ):
            page = await self.open_product_page(slot_id)
        else:
            await self.handle_location_popup(page)
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass

        return page

    # =========================================================
    # SAVE SESSION + PHONE METADATA
    # =========================================================

    async def save_session(self, slot_id: str, phone_number: str | None = None):
        context = self.contexts.get(slot_id)
        if context is None:
            return
        session_dir = self.sessions.session_path(slot_id)
        storage_file = session_dir / "storage_state.json"
        try:
            await context.storage_state(path=str(storage_file))
        except Exception:
            pass

        if phone_number:
            meta_file = session_dir / "meta.json"
            try:
                meta_file.write_text(json.dumps({"phone_number": phone_number}))
            except Exception:
                pass

    def load_saved_phone(self, slot_id: str) -> str | None:
        try:
            session_dir = self.sessions.session_path(slot_id)
            meta_file = session_dir / "meta.json"
            if meta_file.exists():
                data = json.loads(meta_file.read_text())
                return data.get("phone_number")
        except Exception:
            pass
        return None

    async def close_slot(self, slot_id: str):
        context = self.contexts.pop(slot_id, None)
        if context is None:
            return
        try:
            await context.close()
        except Exception:
            pass

    async def logout_slot(self, slot_id: str):
        await self.close_slot(slot_id)
        self.sessions.delete_session(slot_id)

    async def close(self):
        for slot_id in list(self.contexts.keys()):
            await self.close_slot(slot_id)

        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self.playwright is not None:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
