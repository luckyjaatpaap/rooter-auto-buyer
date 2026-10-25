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

    WINDOW_WIDTH = 1280
    WINDOW_HEIGHT = 720

    # Real Human Windows Chrome User-Agent
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    )

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
                    "--disable-blink-features=AutomationControlled",
                    f"--window-size={self.WINDOW_WIDTH},{self.WINDOW_HEIGHT}",
                    "--force-device-scale-factor=1",
                    "--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-default-apps",
                    "--metrics-recording-only",
                    "--mute-audio",
                    "--no-first-run",
                    "--lang=en-IN,en",
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
            "viewport": {
                "width": self.WINDOW_WIDTH,
                "height": self.WINDOW_HEIGHT,
            },
            "screen": {
                "width": self.WINDOW_WIDTH,
                "height": self.WINDOW_HEIGHT,
            },
            "user_agent": self.USER_AGENT,
            "is_mobile": False,
            "has_touch": False,
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
            "geolocation": {"latitude": 28.6139, "longitude": 77.2090},
            "permissions": ["geolocation"],
            "extra_http_headers": {
                "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
                "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        }

    def get_indian_region_cookies(self):
        """Rooter ko 100% Indian region batane wali cookies taaki popup paida hi na ho."""
        exp = 1893456000  # Year 2030
        return [
            {
                "name": "COUNTRY",
                "value": "IN",
                "domain": "shop.rooter.gg",
                "path": "/",
                "expires": exp,
                "httpOnly": False,
                "secure": False,
                "sameSite": "Lax",
            },
            {
                "name": "COUNTRY",
                "value": "IN",
                "domain": ".rooter.gg",
                "path": "/",
                "expires": exp,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "COUNTRY_LOCALE",
                "value": "en-IN",
                "domain": "shop.rooter.gg",
                "path": "/",
                "expires": exp,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            },
            {
                "name": "LANGUAGE",
                "value": "en",
                "domain": "shop.rooter.gg",
                "path": "/",
                "expires": exp,
                "httpOnly": False,
                "secure": False,
                "sameSite": "Lax",
            },
            {
                "name": "darkMode",
                "value": "true",
                "domain": ".rooter.gg",
                "path": "/",
                "expires": exp,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
        ]

    async def _apply_stealth_and_auto_popup_killer(self, context: BrowserContext):
        """
        1. Indian region cookies pre-inject karta hai.
        2. Anti-bot stealth (navigator.webdriver = false) lagata hai.
        3. Har 300ms par چلने wala auto-clicker lagata hai jo 'No, stay on this site' ko aate hi real human click se daba deta hai.
        """
        try:
            await context.add_cookies(self.get_indian_region_cookies())
        except Exception:
            pass

        await context.add_init_script("""
            // 1. Stealth Anti-Bot Evasion
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en', 'hi'] });
            window.chrome = { runtime: {} };

            // 2. LocalStorage Indian Region Pre-set
            try {
                localStorage.setItem('COUNTRY', 'IN');
                localStorage.setItem('COUNTRY_LOCALE', 'en-IN');
                localStorage.setItem('LANGUAGE', 'en');
            } catch (e) {}

            // 3. Real Human Auto-Clicker for 'No, stay on this site'
            const clickStayOnSite = () => {
                try {
                    const allEls = document.querySelectorAll('button, p, span, div, a');
                    for (const el of allEls) {
                        const directText = (el.innerText || el.textContent || '').trim();
                        if (
                            directText.toLowerCase() === 'no, stay on this site' ||
                            directText.toLowerCase() === 'stay on this site'
                        ) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                ['mousedown', 'mouseup', 'click'].forEach(evtType => {
                                    el.dispatchEvent(new MouseEvent(evtType, {
                                        view: window,
                                        bubbles: true,
                                        cancelable: true,
                                        buttons: 1
                                    }));
                                });
                                if (typeof el.click === 'function') el.click();
                            }
                        }
                    }
                } catch (e) {}
            };

            setInterval(clickStayOnSite, 350);
            document.addEventListener('DOMContentLoaded', () => {
                clickStayOnSite();
                if (document.body) {
                    const obs = new MutationObserver(clickStayOnSite);
                    obs.observe(document.body, { childList: true, subtree: true });
                }
            });
        """)

    async def get_context(self, slot_id: str) -> BrowserContext:
        await self.ensure_browser_alive()

        if slot_id in self.contexts:
            ctx = self.contexts[slot_id]
            try:
                _ = ctx.pages
                return ctx
            except Exception:
                self.contexts.pop(slot_id, None)

        session_dir = self.sessions.session_path(slot_id)
        storage_file = session_dir / "storage_state.json"
        options = self.context_options()

        context = None
        if storage_file.exists() and storage_file.stat().st_size > 10:
            try:
                context = await self.browser.new_context(
                    storage_state=str(storage_file),
                    **options,
                )
            except Exception:
                context = None

        if context is None:
            context = await self.browser.new_context(**options)

        await self._apply_stealth_and_auto_popup_killer(context)
        self.contexts[slot_id] = context
        return context

    async def _attach_playwright_popup_handler(self, page: Page):
        """Playwright native locator handler + pagina-level popup killer."""
        try:
            stay_locator = page.get_by_text("No, stay on this site", exact=False)
            await page.add_locator_handler(
                stay_locator,
                lambda loc: loc.first.click(force=True, timeout=1500),
                no_wait_after=True,
            )
        except Exception:
            pass

    async def get_page(self, slot_id: str) -> Page:
        context = await self.get_context(slot_id)

        try:
            valid_pages = [p for p in context.pages if not p.is_closed()]
            if valid_pages:
                for extra_page in valid_pages[1:]:
                    try:
                        await extra_page.close()
                    except Exception:
                        pass
                return valid_pages[0]

            page = await context.new_page()
            await self._attach_playwright_popup_handler(page)
            return page
        except Exception:
            self.contexts.pop(slot_id, None)
            context = await self.get_context(slot_id)
            page = await context.new_page()
            await self._attach_playwright_popup_handler(page)
            return page

    async def reset_slot_page(self, slot_id: str) -> Page:
        """Context ko safely close karke fresh storage_state se naya context & tab banata hai."""
        try:
            ctx = self.contexts.pop(slot_id, None)
            if ctx:
                await ctx.close()
        except Exception:
            pass
        return await self.get_page(slot_id)

    # =========================================================
    # ROOTER LOCATION POPUP HANDLER
    # =========================================================

    async def handle_location_popup(self, page: Page, slot_id: str = "SLOT") -> bool:
        """
        1. Exact 'No, stay on this site' leaf element dhoondh kar real mouse click karta hai.
        2. Playwright bounding_box nikal kar exact center par physical mouse click karta hai.
        """
        try:
            await page.wait_for_timeout(300)

            for _ in range(3):
                # Method 1: Find leaf element with exact text and click its bounding box center
                box = await page.evaluate("""() => {
                    const allEls = Array.from(document.querySelectorAll('button, p, span, div, a'));
                    let target = null;
                    for (const el of allEls) {
                        const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (txt === 'no, stay on this site' || txt === 'stay on this site') {
                            target = el;
                            // Prefer the innermost element
                            if (el.children.length === 0) break;
                        }
                    }
                    if (!target) return null;
                    const r = target.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) return null;

                    ['mousedown', 'mouseup', 'click'].forEach(evtType => {
                        target.dispatchEvent(new MouseEvent(evtType, {
                            view: window,
                            bubbles: true,
                            cancelable: true,
                            buttons: 1
                        }));
                    });
                    if (typeof target.click === 'function') target.click();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }""")

                if box and "x" in box and "y" in box:
                    await page.mouse.move(box["x"], box["y"], steps=5)
                    await page.mouse.click(box["x"], box["y"])
                    await page.wait_for_timeout(500)
                    return True

                # Method 2: Playwright Locator fallback
                loc = page.get_by_text("No, stay on this site", exact=False)
                if await loc.count() > 0 and await loc.last.is_visible(timeout=400):
                    await loc.last.click(force=True, timeout=1500)
                    await page.wait_for_timeout(500)
                    return True

                await page.wait_for_timeout(250)

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
        await self.handle_location_popup(page, slot_id)
        await page.wait_for_timeout(1000)
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
            await self.handle_location_popup(page, slot_id)
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
        session_dir.mkdir(parents=True, exist_ok=True)
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
