import asyncio
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from .browser import BrowserManager
from .config import settings
from .state import AccountState
from .telegram import TelegramBot


class AccountController:

    def __init__(
        self,
        browser: BrowserManager,
        telegram: TelegramBot,
    ):
        self.browser = browser
        self.telegram = telegram

        self.accounts: Dict[str, AccountState] = {}

        self.screenshots_dir = Path(settings.screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.stock_event = asyncio.Event()
        self.sniper_tasks: Dict[str, asyncio.Task] = {}

        self._create_slots()

    # =========================================================
    # SLOT MANAGEMENT & AUTO SESSION RESTORE
    # =========================================================

    def _create_slots(self):
        service_number = settings.current_service_id
        for account_number in range(1, settings.accounts_per_service + 1):
            slot_id = f"S{service_number}-A{account_number}"
            state = AccountState(slot_id=slot_id)

            # Volume se saved session aur phone number auto-load karna
            try:
                session_dir = self.browser.sessions.session_path(slot_id)
                storage_file = session_dir / "storage_state.json"
                if storage_file.exists() and storage_file.stat().st_size > 10:
                    saved_phone = self.browser.load_saved_phone(slot_id)
                    state.logged_in = True
                    state.active = True
                    state.phone_number = saved_phone
                    state.current_page = "✅ Session Restored (Auto-Starting...)"
            except Exception:
                pass

            self.accounts[slot_id] = state

    def _ensure_snipers_running(self) -> int:
        """Jo bhi accounts logged in hain aur unka sniper band hai, unhe turant chalu karega."""
        started = 0
        for slot_id, acc in self.accounts.items():
            if acc.logged_in:
                task = self.sniper_tasks.get(slot_id)
                if task is None or task.done():
                    self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))
                    started += 1
        return started

    def get_account(self, slot_id: str) -> AccountState:
        account = self.accounts.get(slot_id)
        if account is None:
            raise ValueError(f"Unknown slot: {slot_id}")
        return account

    def all_accounts(self):
        return list(self.accounts.values())

    # =========================================================
    # COMMAND CONNECTION
    # =========================================================

    def connect_commands(self):
        self.telegram.register_command("start", self.handle_start)
        self.telegram.register_command("status", self.handle_status)
        self.telegram.register_command("login", self.handle_login)
        self.telegram.register_command("otp", self.handle_otp)
        self.telegram.register_command("logout", self.handle_logout)
        self.telegram.register_command("screen", self.handle_screen)
        self.telegram.register_command("refresh", self.handle_refresh)
        self.telegram.register_command("help", self.handle_help)
        self.telegram.register_command("sniper", self.handle_sniper_mode)
        self.telegram.register_command("stop_sniper", self.handle_stop_sniper)
        self.telegram.register_command("trigger_buy", self.handle_trigger_buy)
        self.telegram.register_command("heal", self.handle_heal)

    # =========================================================
    # START / HELP / STATUS / HEAL
    # =========================================================

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        auto_started = self._ensure_snipers_running()
        extra_msg = f"\n🚀 Auto-resumed {auto_started} saved sessions!" if auto_started > 0 else ""
        await update.message.reply_text(
            "🤖 Rooter Auto Buyer (Swarm Pro Mode)\n\n"
            f"Total slots: {settings.total_slots}\n"
            f"Current Service ID: {settings.current_service_id}\n"
            f"Accounts/service: {settings.accounts_per_service}\n"
            f"{extra_msg}\n"
            "System Online & Swarm-Ready. Use /status to monitor."
        )

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📖 SWARM PRO COMMANDS LIST\n\n"
            "/status - Live status, balance & last check time\n"
            "/login S1-A1 9876543210 - Login account\n"
            "/otp S1-A1 123456 - Submit OTP\n"
            "/screen S1-A1 - Live page screenshot\n"
            "/refresh S1-A1 - Hard refresh & start sniper\n"
            "/trigger_buy - Wake up ALL accounts & check stock NOW\n"
            "/sniper all - Start sniper on all logged-in slots\n"
            "/stop_sniper all - Pause sniper without logging out\n"
            "/heal - Clean RAM & restart browser tabs safely\n"
            "/logout S1-A1 - Logout & delete saved session"
        )

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._ensure_snipers_running()
        lines = ["📊 SWARM ACCOUNT STATUS", ""]

        for account in self.all_accounts():
            phone = account.phone_number if account.phone_number else "Saved Session"
            login_state = "✅ LOGGED IN" if account.logged_in else "❌ NOT LOGGED IN"
            task = self.sniper_tasks.get(account.slot_id)
            sniper_state = "🔫 SNIPER: ON" if (task and not task.done()) else "🔫 SNIPER: OFF"
            balance = f"₹{account.wallet_balance:.2f}" if account.wallet_balance is not None else "-"

            lines.append(f"🆔 {account.slot_id} | {login_state} | {sniper_state}")
            if account.logged_in:
                lines.append(f"  📱 Num: {phone} | Bal: {balance}")

            lines.append(f"  📍 State: {account.current_page}")

            if account.last_error:
                lines.append(f"  ⚠️ Note: {account.last_error}")

            lines.append("")

        await update.message.reply_text("\n".join(lines))

    async def handle_heal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🧹 Healing browser & cleaning RAM for all active slots...")
        healed = 0
        for slot_id, acc in self.accounts.items():
            if acc.logged_in:
                try:
                    await self.browser.save_session(slot_id, acc.phone_number)
                    await self.browser.reset_slot_page(slot_id)
                    acc.update(current_page="✨ Healed & Fresh", last_error=None)
                    healed += 1
                except Exception:
                    pass
        self._ensure_snipers_running()
        await update.message.reply_text(f"✅ RAM cleaned & {healed} slots refreshed! All snipers running.")

    # =========================================================
    # LOGIN / OTP HELPER LOCATORS & BALANCE PARSER
    # =========================================================

    async def _update_live_balance(self, page, account: AccountState) -> str:
        wallet_balance_text = "Balance info not found"
        try:
            balance_locator = page.locator("text=/Wallet Balance/i >> visible=true").first
            if await balance_locator.is_visible(timeout=1500):
                wallet_balance_text = await balance_locator.inner_text()
                nums = re.findall(r"\d+(?:\.\d+)?", wallet_balance_text.replace(",", ""))
                if nums:
                    account.update(wallet_balance=float(nums[0]))
        except Exception:
            pass
        return wallet_balance_text

    async def _find_mobile_input(self, page):
        selectors = [
            'input[type="tel"]', 'input[inputmode="tel"]', 'input[name="phone"]',
            'input[placeholder*="mobile" i]', 'input[placeholder*="number" i]'
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                for index in range(await locator.count()):
                    item = locator.nth(index)
                    if await item.is_visible(timeout=300):
                        ph = await item.get_attribute("placeholder")
                        if ph and "search" in ph.lower():
                            continue
                        return item
            except Exception:
                pass
        return None

    async def _open_login_popup(self, page):
        await asyncio.sleep(2)

        # 1. Agar login form pehle se khula hai, use reuse karo
        mobile_input = await self._find_mobile_input(page)
        if mobile_input is not None:
            return mobile_input

        # 2. Profile/account/login buttons aur links dhoondo
        profile_selectors = [
            'header [aria-label*="profile" i]',
            'header [aria-label*="account" i]',
            'header [aria-label*="user" i]',
            'header [title*="profile" i]',
            'header [title*="account" i]',
            'header a[href*="login" i]',
            'header a[href*="account" i]',
            'header a[href*="profile" i]',
            'header button',
            'header a',
            'header [role="button"]',
            'button[aria-label*="profile" i]',
            'button[aria-label*="account" i]',
            'button[aria-label*="login" i]',
            'button[title*="profile" i]',
            'button[title*="account" i]',
        ]

        clicked = False

        for selector in profile_selectors:
            try:
                elements = page.locator(selector)
                count = min(await elements.count(), 30)

                for index in range(count):
                    item = elements.nth(index)

                    try:
                        if not await item.is_visible(timeout=700):
                            continue

                        details = await item.evaluate("""el => ({
                            text: (el.innerText || '').trim().toLowerCase(),
                            aria: (el.getAttribute('aria-label') || '').toLowerCase(),
                            title: (el.getAttribute('title') || '').toLowerCase(),
                            href: (el.getAttribute('href') || '').toLowerCase(),
                            testid: (el.getAttribute('data-testid') || '').toLowerCase(),
                            html: el.outerHTML.slice(0, 500)
                        })""")

                        text = details.get("text", "")
                        aria = details.get("aria", "")
                        title = details.get("title", "")
                        href = details.get("href", "")
                        testid = details.get("testid", "")
                        html = details.get("html", "").lower()

                        # Sirf login/profile/account se related element click karo
                        keywords = (
                            "profile", "account", "login", "log in",
                            "sign in", "signin", "user"
                        )

                        has_keyword = any(
                            word in value
                            for value in (text, aria, title, href, testid, html)
                            for word in keywords
                        )

                        # Header ke har button ko blindly click mat karo
                        if not has_keyword:
                            continue

                        print(
                            "ROOTER PROFILE CANDIDATE:",
                            selector,
                            details
                        )

                        await item.click(timeout=3000)
                        clicked = True
                        print("ROOTER PROFILE CLICKED:", selector)
                        await asyncio.sleep(2)

                        mobile_input = await self._find_mobile_input(page)
                        if mobile_input is not None:
                            print("ROOTER MOBILE INPUT FOUND")
                            return mobile_input

                        # Click ke baad popup animation/load hone ka wait
                        for _ in range(6):
                            await asyncio.sleep(0.5)
                            mobile_input = await self._find_mobile_input(page)
                            if mobile_input is not None:
                                print("ROOTER MOBILE INPUT FOUND AFTER WAIT")
                                return mobile_input

                    except Exception as exc:
                        print("Profile candidate skipped:", str(exc)[:180])
                        continue

            except Exception as exc:
                print("Profile selector failed:", selector, str(exc)[:150])

        # 3. Diagnose karo; galat element click karke aage mat badho
        try:
            diagnostic = await page.evaluate("""() => ({
                url: location.href,
                title: document.title,
                header: Array.from(document.querySelectorAll(
                    'header button, header a, header [role="button"]'
                )).filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }).map(el => ({
                    text: (el.innerText || '').trim().slice(0, 80),
                    aria: el.getAttribute('aria-label'),
                    title: el.getAttribute('title'),
                    href: el.getAttribute('href'),
                    html: el.outerHTML.slice(0, 350)
                })).slice(0, 35),
                inputs: Array.from(document.querySelectorAll('input'))
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }).map(el => ({
                        type: el.type,
                        placeholder: el.placeholder,
                        name: el.name
                    }))
            })""")

            print("ROOTER PROFILE DIAGNOSTICS:", diagnostic)

        except Exception as exc:
            print("ROOTER DIAGNOSTICS FAILED:", str(exc))

        print("ROOTER LOGIN POPUP NOT FOUND. Profile click attempted:", clicked)
        return await self._find_mobile_input(page)


    async def _find_send_otp_button(self, page):
        candidates = [
            page.get_by_role("button", name="Continue", exact=False),
            page.locator("button:has-text('Continue')"),
            page.locator("button:has-text('CONTINUE')"),
            page.locator("text=Continue"),
            page.locator("button:has-text('Send OTP')")
        ]
        for locator in candidates:
            try:
                if await locator.count() > 0 and await locator.first.is_visible(timeout=300):
                    return locator.first
            except Exception:
                pass
        return None

    async def _find_otp_inputs(self, page):
        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[placeholder*="OTP" i]',
            'input[inputmode="numeric"]',
            'input[type="tel"]',
            'input[type="number"]'
        ]

        found = []
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    item = locator.nth(index)
                    if await item.is_visible(timeout=300):
                        found.append(item)
                if found:
                    return found
            except Exception:
                continue

        if not found:
            try:
                inputs = page.locator('input')
                count = await inputs.count()
                for i in range(count):
                    el = inputs.nth(i)
                    if await el.is_visible(timeout=200):
                        type_attr = await el.get_attribute("type")
                        if type_attr in ["tel", "number", "text"]:
                            found.append(el)
                if len(found) >= 6:
                    return found[:8]
            except Exception:
                pass

        return found

    async def _find_verify_button(self, page):
        candidates = [
            page.locator("button:has-text('Verify')"),
            page.get_by_role("button", name="Verify Now", exact=False),
            page.get_by_text("Verify", exact=False)
        ]
        for locator in candidates:
            try:
                if await locator.count() > 0 and await locator.first.is_visible(timeout=300):
                    return locator.first
            except Exception:
                pass
        return None

    # =========================================================
    # LOGIN & OTP & SCREEN & LOGOUT
    # =========================================================

    async def handle_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            if len(args) < 2:
                return await update.message.reply_text("❌ Format:\n/login S1-A1 9876543210")
            slot_id, phone_number = args[0].upper(), args[1].strip()

            account = self.get_account(slot_id)
            if account.logged_in:
                return await update.message.reply_text(f"⚠️ {slot_id} pehle se logged in hai. Logout ke liye /logout {slot_id} karein.")
            if not phone_number.isdigit() or len(phone_number) != 10:
                return await update.message.reply_text("❌ Valid 10-digit mobile number daal bhai.")

            await update.message.reply_text(f"🔍 Opening product page for {slot_id}...")

            page = await self.browser.open_product_page(slot_id)

            try:
                await self.browser.handle_location_popup(page)
                await asyncio.sleep(1.5)
            except Exception:
                pass

            account.update(phone_number=phone_number, active=True, current_page="🔐 Handling Login", last_error=None)

            mobile_input = await self._open_login_popup(page)
            if mobile_input is None:
                screenshot_path = self.screenshots_dir / f"{slot_id}_login_error.png"
                await page.screenshot(path=str(screenshot_path), full_page=False)
                await self.telegram.send_photo(photo_path=str(screenshot_path), caption="❌ Login popup nahi khula.")
                if screenshot_path.exists():
                    screenshot_path.unlink()
                raise RuntimeError("Login popup not opened.")

            await mobile_input.focus()
            await page.keyboard.type(phone_number, delay=50)
            await asyncio.sleep(1.0)

            send_otp_button = await self._find_send_otp_button(page)
            if send_otp_button is None:
                error_ss = self.screenshots_dir / f"{slot_id}_continue_btn_err.png"
                await page.screenshot(path=str(error_ss), full_page=False)
                await self.telegram.send_photo(photo_path=str(error_ss), caption="❌ Continue button nahi mila.")
                if error_ss.exists():
                    error_ss.unlink()
                raise RuntimeError("Continue button not found.")

            await send_otp_button.evaluate("(el) => { el.removeAttribute('disabled'); el.removeAttribute('data-disabled'); el.disabled = false; }")
            await send_otp_button.click(force=True, timeout=3000)

            for _ in range(40):
                await asyncio.sleep(0.5)
                if await self._find_otp_inputs(page):
                    break
            else:
                error_ss = self.screenshots_dir / f"{slot_id}_otp_popup_err.png"
                await page.screenshot(path=str(error_ss), full_page=False)
                await self.telegram.send_photo(photo_path=str(error_ss), caption="❌ OTP box nahi aaya.")
                if error_ss.exists():
                    error_ss.unlink()
                raise RuntimeError("OTP popup did not appear.")

            account.update(current_page="📩 OTP Sent. Waiting...", last_error=None)
            await update.message.reply_text(f"📩 OTP sent for {slot_id}.\nAb bhej: `/otp {slot_id} 123456`")
        except Exception as exc:
            try:
                account.update(last_error=str(exc), active=False)
            except Exception:
                pass
            await update.message.reply_text(f"❌ Login start failed: {exc}")

    async def handle_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            if len(args) < 2:
                return await update.message.reply_text("❌ Format:\n/otp S1-A1 123456")
            slot_id, otp = args[0].upper(), args[1].strip()

            account = self.get_account(slot_id)
            if len(otp) not in [6, 8] or not otp.isdigit():
                return await update.message.reply_text("❌ OTP 6 ya 8 digit ka number hona chahiye.")

            page = await self.browser.get_page(slot_id)

            otp_inputs = []
            for _ in range(20):
                otp_inputs = await self._find_otp_inputs(page)
                if otp_inputs and (len(otp_inputs) == 1 or len(otp_inputs) >= len(otp)):
                    break
                await asyncio.sleep(0.5)

            if not otp_inputs:
                raise RuntimeError("OTP fields page par nahi mile.")

            if len(otp_inputs) == 1:
                await otp_inputs[0].focus()
                await page.keyboard.type(otp, delay=50)
            else:
                boxes = otp_inputs[:len(otp)]
                for i, digit in enumerate(otp):
                    if i < len(boxes):
                        await boxes[i].focus()
                        await page.keyboard.press(digit)
                        await asyncio.sleep(0.05)

            await asyncio.sleep(1.0)

            verify_button = await self._find_verify_button(page)
            if verify_button is None:
                raise RuntimeError("Verify button nahi mila.")

            await verify_button.evaluate("(el) => { el.removeAttribute('disabled'); el.removeAttribute('data-disabled'); el.disabled = false; }")
            await verify_button.click(force=True, timeout=3000)
            await asyncio.sleep(3.5)

            page = await self.browser.ensure_product_page(slot_id)
            await self.browser.save_session(slot_id, account.phone_number)
            account.update(logged_in=True, active=True, current_page="✅ Logged In & Saved", last_error=None)
            await update.message.reply_text(f"✅ Login successful & Session Saved for {slot_id}!")

            task = self.sniper_tasks.get(slot_id)
            if task is None or task.done():
                self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))
                await update.message.reply_text(f"🔫 Sniper AUTO-STARTED for {slot_id}!")

        except Exception as exc:
            try:
                account.update(last_error=str(exc))
            except Exception:
                pass
            await update.message.reply_text(f"❌ OTP failed: {exc}")

    async def handle_screen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args:
                return await update.message.reply_text("❌ Format:\n/screen S1-A1")
            slot_id = context.args[0].upper()
            account = self.get_account(slot_id)

            page = await self.browser.ensure_product_page(slot_id)
            screenshot_path = self.screenshots_dir / f"{slot_id}.png"
            await page.screenshot(path=str(screenshot_path), full_page=False)
            await self.telegram.send_photo(photo_path=str(screenshot_path), caption=f"🖥 {slot_id}\nState: {account.current_page}")
            if screenshot_path.exists():
                screenshot_path.unlink()
        except Exception as exc:
            try:
                account.update(last_error=str(exc))
            except Exception:
                pass
            await update.message.reply_text(f"❌ Screenshot failed: {exc}")

    async def handle_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args:
                return await update.message.reply_text("❌ Format:\n/refresh S1-A1")
            slot_id = context.args[0].upper()
            account = self.get_account(slot_id)

            page = await self.browser.reset_slot_page(slot_id)
            cb = int(time.time())
            fresh_url = f"{settings.product_url}?cb={cb}" if "?" not in settings.product_url else f"{settings.product_url}&cb={cb}"
            await page.goto(fresh_url, wait_until="domcontentloaded", timeout=45000)

            account.update(logged_in=True, active=True, current_page="🔄 Manually Refreshed", last_error=None)
            await update.message.reply_text(f"🔄 Hard Refreshed {slot_id}")

            task = self.sniper_tasks.get(slot_id)
            if task is None or task.done():
                self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))
                await update.message.reply_text(f"🔫 Sniper AUTO-STARTED for {slot_id}!")

        except Exception as exc:
            try:
                account.update(last_error=str(exc))
            except Exception:
                pass
            await update.message.reply_text(f"❌ Refresh failed: {exc}")

    async def handle_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args:
                return await update.message.reply_text("❌ Format:\n/logout S1-A1")
            slot_id = context.args[0].upper()
            account = self.get_account(slot_id)

            # 1. Sniper task ko rokna
            task = self.sniper_tasks.pop(slot_id, None)
            if task and not task.done():
                task.cancel()

            # 2. Browser RAM se tab/context permanently close karna
            await self.browser.close_slot(slot_id)

            # 3. Volume se session data aur files delete karna
            self.browser.sessions.delete_session(slot_id)
            
            # Extra: Meta file (phone number) bhi delete karna agar ho toh
            try:
                session_dir = self.browser.sessions.session_path(slot_id)
                meta_file = session_dir / "meta.json"
                if meta_file.exists():
                    meta_file.unlink()
            except Exception:
                pass

            # State ko fresh reset karna
            account.update(
                phone_number=None,
                logged_in=False,
                active=False,
                current_page="unknown",
                last_error=None,
                wallet_balance=None
            )
            
            await update.message.reply_text(f"🚪 Successfully logged out & RAM freed for {slot_id}. Slot is now fresh for a new account!")
        except Exception as exc:
            await update.message.reply_text(f"❌ Logout failed: {exc}")


    # =========================================================
    # 🎯 SWARM ATTACK SNIPER BACKGROUND WORKER (SELF-HEALING)
    # =========================================================
    async def _sniper_worker(self, slot_id: str):
        account = self.get_account(slot_id)

        # Smart Stagger: Har slot ko 4-4 second ke gap par start karega taaki ek sath CPU spike na ho
        try:
            slot_num = int(slot_id.split("-A")[-1])
            await asyncio.sleep((slot_num - 1) * 4)
        except Exception:
            pass

        await self.telegram.send_message(f"🎯 Swarm Sniper ACTIVATED for {slot_id}. 30s Auto-Refresh running...")

        cycle_count = 0

        while account.logged_in:
            try:
                cycle_count += 1
                if cycle_count % 50 == 0:
                    try:
                        await self.browser.save_session(slot_id, account.phone_number)
                        await self.browser.reset_slot_page(slot_id)
                    except Exception:
                        pass

                # 1. 30-SECOND WAIT PHASE (OR SWARM TRIGGERED)
                last_time = datetime.now().strftime("%I:%M:%S %p")
                account.update(current_page=f"⏳ [STAGE: 30s Wait] (Last: {last_time})", last_error=None)

                try:
                    await asyncio.wait_for(self.stock_event.wait(), timeout=30.0)
                    account.update(current_page="⚡ [STAGE: Swarm Triggered! Attacking!]")
                except asyncio.TimeoutError:
                    pass

                if not account.logged_in:
                    break

                page = await self.browser.get_page(slot_id)

                # 2. ANTI-CACHE HARD REFRESH
                account.update(current_page="🔄 [STAGE: Hard Refreshing Page]")
                cache_buster = int(time.time())
                fresh_url = f"{settings.product_url}?cb={cache_buster}" if "?" not in settings.product_url else f"{settings.product_url}&cb={cache_buster}"

                await page.goto(fresh_url, wait_until="domcontentloaded", timeout=35000)
                try:
                    await self.browser.handle_location_popup(page)
                except Exception:
                    pass
                await asyncio.sleep(2.0)

                content = await page.content()
                if "Application error: a client-side exception" in content:
                    account.update(last_error="Website White Screen - Auto Retrying")
                    await asyncio.sleep(4.0)
                    continue

                # 3. AGGRESSIVE 5000 SELECTION
                account.update(current_page="🎯 [STAGE: Selecting Rs.5000]")
                rs_5000_locator = page.locator("text=Rs.5000 Wallet Code >> visible=true")

                if await rs_5000_locator.count() > 0:
                    try:
                        await rs_5000_locator.first.click(force=True, timeout=3000)
                        await rs_5000_locator.first.evaluate("(el) => { if(el.parentElement) el.parentElement.click(); }")
                    except Exception as click_err:
                        account.update(last_error=f"Click Note: {str(click_err)[:40]}")
                else:
                    fallback_loc = page.locator("text=5000 >> visible=true")
                    if await fallback_loc.count() > 0:
                        try:
                            await fallback_loc.last.click(force=True, timeout=3000)
                            await fallback_loc.last.evaluate("(el) => { if(el.parentElement) el.parentElement.click(); }")
                        except Exception as click_err:
                            account.update(last_error=f"Fallback Note: {str(click_err)[:40]}")
                    else:
                        account.update(last_error="Rs.5000 option not visible")

                await asyncio.sleep(1.5)
                await self._update_live_balance(page, account)

                # 4. STOCK CHECK RADAR
                account.update(current_page="🔍 [STAGE: Checking for Pay Button]")
                pay_btn_1 = page.locator("button >> text='Pay via wallet' >> visible=true").first
                is_in_stock = False
                try:
                    is_in_stock = await pay_btn_1.is_visible(timeout=2500)
                except Exception:
                    pass

                if not is_in_stock:
                    check_t = datetime.now().strftime("%I:%M:%S %p")
                    account.update(current_page=f"😴 [STAGE: Out of Stock] (Checked: {check_t})")
                    await asyncio.sleep(1.5)
                    continue

                # ==========================================
                # 🚨 STOCK DETECTED - TRIGGER SWARM & BUY
                # ==========================================
                account.update(current_page="🚨 [STAGE: INITIATING SWARM BUY FLOW!]")
                
                # 🔥 Yahan baki saare accounts ki neend todne ke liye trigger bhej diya
                if not self.stock_event.is_set():
                    self.stock_event.set()
                    # 3 second baad event clear ho jayega taaki loop normal chale
                    asyncio.create_task(self._clear_stock_event_delayed())

                await self.telegram.send_message(f"🚨 STOCK DETECTED in {slot_id}! Swarm attack initiated across all accounts...")

                for target_qty in [2, 1]:
                    try:
                        if target_qty == 1:
                            account.update(current_page="🔄 [STAGE: Retrying with Qty 1]")
                            retry_url = f"{settings.product_url}?retry={int(time.time())}" if "?" not in settings.product_url else f"{settings.product_url}&retry={int(time.time())}"
                            await page.goto(retry_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(2.0)

                            rs_5000_loc = page.locator("text=Rs.5000 Wallet Code >> visible=true")
                            if await rs_5000_loc.count() > 0:
                                await rs_5000_loc.first.click(force=True)
                                await rs_5000_loc.first.evaluate("(el) => { if(el.parentElement) el.parentElement.click(); }")
                                await asyncio.sleep(1.5)

                            pay_btn_1 = page.locator("button >> text='Pay via wallet' >> visible=true").first

                        if target_qty == 2:
                            account.update(current_page="➕ [STAGE: Changing Quantity to 2]")
                            try:
                                plus_btn = page.locator("button:has-text('+') >> visible=true").first
                                await plus_btn.wait_for(state="visible", timeout=3000)
                                await plus_btn.click(force=True, timeout=2000)
                                await plus_btn.evaluate("(el) => el.click()")
                                await asyncio.sleep(1.5)
                            except Exception as e:
                                account.update(last_error=f"Plus Btn Note: {str(e)[:40]}")

                        account.update(current_page="💰 [STAGE: Checking Balance]")
                        wallet_balance_text = await self._update_live_balance(page, account)

                        account.update(current_page="📸 [STAGE: Taking Verification Screenshot]")
                        screenshot_path = self.screenshots_dir / f"{slot_id}_pre_buy_qty_{target_qty}.png"
                        try:
                            await page.screenshot(path=str(screenshot_path), full_page=False)
                            await self.telegram.send_photo(
                                photo_path=str(screenshot_path),
                                caption=(f"🛒 SWARM BUY ATTEMPT (Qty {target_qty})!\n\nSlot: {slot_id}\nBalance Info: {wallet_balance_text}")
                            )
                            if screenshot_path.exists():
                                screenshot_path.unlink()
                        except Exception:
                            pass

                        if "insufficient" in wallet_balance_text.lower() or "add money" in wallet_balance_text.lower():
                            account.update(current_page="🛑 [STAGE: Stopped - Insufficient Funds]")
                            await self.telegram.send_message(f"🚨 INSUFFICIENT BALANCE in {slot_id}. Buy stopped.")
                            break

                        account.update(current_page="💳 [STAGE: Clicking First Pay Button]")
                        await pay_btn_1.wait_for(state="visible", timeout=5000)
                        await pay_btn_1.click(force=True, timeout=3000)
                        await pay_btn_1.evaluate("(el) => el.click()")

                        account.update(current_page="📝 [STAGE: Waiting for Delivery Popup]")
                        await page.locator("text=Delivery Details >> visible=true").wait_for(state="visible", timeout=6000)
                        await asyncio.sleep(1.5)

                        account.update(current_page="💳 [STAGE: Clicking Final Pay Button]")
                        pay_btn_2 = page.locator("button >> text='Pay via wallet' >> visible=true").last
                        await pay_btn_2.wait_for(state="visible", timeout=5000)
                        await pay_btn_2.click(force=True, timeout=3000)
                        await pay_btn_2.evaluate("(el) => el.click()")

                        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        account.update(current_page="✅ [STAGE: SUCCESS - Code Bought!]")
                        await self.telegram.send_message(
                            f"✅✅ SWARM SUCCESS: CODE PURCHASED!\n"
                            f"Amount: Rs.5000\nQty: {target_qty}\nSlot: {slot_id}\nTime: {current_time}"
                        )
                        break

                    except Exception as flow_err:
                        account.update(last_error=f"Buy Flow Qty {target_qty} Error: {str(flow_err)[:50]}")
                        error_ss = self.screenshots_dir / f"{slot_id}_error_qty_{target_qty}.png"
                        try:
                            await page.screenshot(path=str(error_ss), full_page=False)
                            await self.telegram.send_photo(photo_path=str(error_ss), caption=f"⚠️ Failed Qty {target_qty} for {slot_id}")
                            if error_ss.exists():
                                error_ss.unlink()
                        except Exception:
                            pass

                        if target_qty == 2:
                            await self.telegram.send_message(f"🔄 {slot_id} retrying with Quantity 1...")
                        else:
                            account.update(current_page="❌ [STAGE: Buy Flow Failed Completely]")
                            await self.telegram.send_message(f"❌ {slot_id} failed completely.")

                await asyncio.sleep(5.0)

            except asyncio.CancelledError:
                account.update(current_page="⏸️ Sniper Paused")
                break
            except Exception as loop_err:
                err_msg = str(loop_err)
                account.update(
                    current_page="🛠️ [STAGE: Auto-Healing Tab...]",
                    last_error=f"Self-Healed: {err_msg[:45]}"
                )
                try:
                    await self.browser.reset_slot_page(slot_id)
                except Exception:
                    pass
                await asyncio.sleep(3.0)

        self.sniper_tasks.pop(slot_id, None)

    async def _clear_stock_event_delayed(self):
        await asyncio.sleep(3.0)
        self.stock_event.clear()

    # =========================================================
    # START / STOP SNIPER & MANUAL TRIGGER
    # =========================================================

    async def handle_sniper_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            target = args[0].lower() if args else "all"

            if target == "all":
                started = self._ensure_snipers_running()
                await update.message.reply_text(f"🔫 Swarm Sniper active/started! ({started} newly launched)")
            else:
                slot_id = target.upper()
                acc = self.get_account(slot_id)
                if not acc.logged_in:
                    return await update.message.reply_text(f"❌ {slot_id} is not logged in!")
                task = self.sniper_tasks.get(slot_id)
                if task is None or task.done():
                    self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))
                    await update.message.reply_text(f"🔫 Sniper started for {slot_id}")
                else:
                    await update.message.reply_text(f"✅ Sniper is already running on {slot_id}")
        except Exception as exc:
            await update.message.reply_text(f"❌ Error: {exc}")

    async def handle_stop_sniper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            target = args[0].lower() if args else "all"

            if target == "all":
                stopped = 0
                for slot_id, task in list(self.sniper_tasks.items()):
                    if task and not task.done():
                        task.cancel()
                        stopped += 1
                    self.sniper_tasks.pop(slot_id, None)
                await update.message.reply_text(f"⏸️ Paused sniper on {stopped} accounts.")
            else:
                slot_id = target.upper()
                task = self.sniper_tasks.pop(slot_id, None)
                if task and not task.done():
                    task.cancel()
                    await update.message.reply_text(f"⏸️ Sniper paused for {slot_id}")
                else:
                    await update.message.reply_text(f"ℹ️ Sniper was not running on {slot_id}")
        except Exception as exc:
            await update.message.reply_text(f"❌ Error: {exc}")

    async def trigger_stock_buy(self):
        self.stock_event.set()
        await asyncio.sleep(3.0)
        self.stock_event.clear()

    async def handle_trigger_buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🚨 SWARM TRIGGER SENT! Waking up ALL accounts to attack stock NOW!")
        await self.trigger_stock_buy()
