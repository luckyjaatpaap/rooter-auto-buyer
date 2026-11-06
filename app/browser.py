import asyncio
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

    WINDOW_WIDTH = 1366
    WINDOW_HEIGHT = 768

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Optional[Browser] = None
        self.contexts: Dict[str, BrowserContext] = {}
        self.slot_locks: Dict[str, asyncio.Lock] = {}
        self.sessions = SessionManager()

    def get_slot_lock(self, slot_id: str) -> asyncio.Lock:
        slot_id = slot_id.upper()
        if slot_id not in self.slot_locks:
            self.slot_locks[slot_id] = asyncio.Lock()
        return self.slot_locks[slot_id]

    async def start(self):
        if self.playwright is None:
            self.playwright = await async_playwright().start()

        if self.browser is None or not self.browser.is_connected():
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu",
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certificate-errors",
                    "--ignore-certificate-errors-spki-list",
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
                ],
            )

    async def ensure_browser_alive(self):
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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "CF-IPCountry": "IN",
                "X-Forwarded-For": "103.251.144.1",
            },
        }

    def get_indian_region_cookies(self):
        exp = 1893456000
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
        try:
            await context.add_cookies(self.get_indian_region_cookies())
        except Exception:
            pass

        await context.add_init_script("""
            // Hide webdriver and automation flags completely
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en', 'hi'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            
            window.chrome = {
                runtime: {}
            };

            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            try {
                localStorage.setItem('COUNTRY', 'IN');
                localStorage.setItem('COUNTRY_LOCALE', 'en-IN');
                localStorage.setItem('LANGUAGE', 'en');
            } catch (e) {}

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
        """)

    async def get_context(self, slot_id: str) -> BrowserContext:
        slot_id = slot_id.upper()
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

    async def get_page(self, slot_id: str) -> Page:
        slot_id = slot_id.upper()
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
            return page
        except Exception:
            self.contexts.pop(slot_id, None)
            context = await self.get_context(slot_id)
            return await context.new_page()

    async def reset_slot_page(self, slot_id: str) -> Page:
        slot_id = slot_id.upper()
        try:
            ctx = self.contexts.pop(slot_id, None)
            if ctx:
                await ctx.close()
        except Exception:
            pass
        return await self.get_page(slot_id)

    async def handle_location_popup(self, page: Page, slot_id: str = "SLOT") -> bool:
        try:
            await page.wait_for_timeout(300)
            for _ in range(3):
                box = await page.evaluate("""() => {
                    const allEls = Array.from(document.querySelectorAll('button, p, span, div, a'));
                    let target = null;
                    for (const el of allEls) {
                        const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (txt === 'no, stay on this site' || txt === 'stay on this site') {
                            target = el;
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
                await page.wait_for_timeout(250)
            return False
        except Exception:
            return False

    async def open_product_page(self, slot_id: str) -> Page:
        page = await self.get_page(slot_id)
        
        # Open homepage first to set valid session cookies and bypass datacenter security check
        try:
            await page.goto("https://shop.rooter.gg/", wait_until="domcontentloaded", timeout=35000)
            await asyncio.sleep(1.5)
            await self.handle_location_popup(page, slot_id)
        except Exception:
            pass

        # Now navigate to product page safely
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

    async def save_session(self, slot_id: str, phone_number: str | None = None):
        slot_id = slot_id.upper()
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
            session_dir = self.sessions.session_path(slot_id.upper())
            meta_file = session_dir / "meta.json"
            if meta_file.exists():
                data = json.loads(meta_file.read_text())
                return data.get("phone_number")
        except Exception:
            pass
        return None

    async def close_slot(self, slot_id: str):
        context = self.contexts.pop(slot_id.upper(), None)
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
