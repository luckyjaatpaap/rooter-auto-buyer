import asyncio
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

        self._create_slots()

        # =========================================================
        # SNIPER MODE EVENTS & TASKS
        # =========================================================
        self.stock_event = asyncio.Event() 
        self.sniper_tasks: Dict[str, asyncio.Task] = {}

    # =========================================================
    # SLOT MANAGEMENT
    # =========================================================

    def _create_slots(self):
        # Ye settings.current_service_id se apni specific service ke 5 accounts banayega
        service_number = settings.current_service_id
        for account_number in range(1, settings.accounts_per_service + 1):
            slot_id = f"S{service_number}-A{account_number}"
            self.accounts[slot_id] = AccountState(slot_id=slot_id)

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
        
        # New sniper commands
        self.telegram.register_command("sniper", self.handle_sniper_mode)
        self.telegram.register_command("trigger_buy", self.handle_trigger_buy)

    # =========================================================
    # START
    # =========================================================

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Rooter Auto Buyer\n\n"
            "System online.\n"
            f"Total slots: {settings.total_slots}\n"
            f"Current Service ID: {settings.current_service_id}\n"
            f"Accounts/service: {settings.accounts_per_service}\n\n"
            "Use /status to check slots."
        )

    # =========================================================
    # HELP
    # =========================================================

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📖 Commands\n\n"
            "/start\n"
            "/status\n"
            "/login S1-A1 9876543210\n"
            "/otp S1-A1 123456\n"
            "/screen S1-A1\n"
            "/refresh S1-A1\n"
            "/logout S1-A1\n"
            "/sniper all\n"
            "/trigger_buy\n"
            "/help"
        )

    # =========================================================
    # STATUS
    # =========================================================

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lines = ["📊 ACCOUNT STATUS", ""]

        for account in self.all_accounts():
            phone = account.phone_number if account.phone_number else "-"
            login_state = "LOGGED IN" if account.logged_in else "NOT LOGGED IN"
            active_state = "ACTIVE" if account.active else "INACTIVE"
            
            # Check if sniper is active for this slot
            sniper_state = "🔫 SNIPER ON" if account.slot_id in self.sniper_tasks else ""

            balance = (
                f"₹{account.wallet_balance:.2f}"
                if account.wallet_balance is not None
                else "-"
            )

            lines.append(
                f"{account.slot_id} | {login_state} | "
                f"{active_state} | Balance: {balance} {sniper_state}"
            )

            if phone != "-":
                lines.append(f"  📱 {phone}")

            lines.append(f"  📍 {account.current_page}")

            if account.last_error:
                lines.append(f"  ⚠️ {account.last_error}")

        await update.message.reply_text("\n".join(lines))

    # =========================================================
    # FIND MOBILE INPUT
    # =========================================================

    async def _find_mobile_input(self, page):
        selectors = [
            'input[type="tel"]',
            'input[inputmode="tel"]',
            'input[name="phone"]',
            'input[name="mobile"]',
            'input[name="phoneNumber"]',
            'input[autocomplete="tel"]',
            'input[placeholder*="mobile" i]',
            'input[placeholder*="phone" i]',
            'input[placeholder*="number" i]',
            'input[aria-label*="mobile" i]',
            'input[aria-label*="phone" i]',
            'input[aria-label*="number" i]',
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()

                for index in range(count):
                    item = locator.nth(index)
                    if await item.is_visible(timeout=500):
                        return item
            except Exception:
                continue

        return None

    # =========================================================
    # OPEN LOGIN POPUP
    # =========================================================

    async def _open_login_popup(self, page):
        try:
            await self.browser.handle_location_popup(page)
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        mobile_input = await self._find_mobile_input(page)
        if mobile_input is not None:
            return mobile_input

        candidates = [
            page.get_by_text("Login / Sign Up", exact=True),
            page.get_by_text("Login", exact=True),
            page.get_by_text("Sign Up", exact=True),
        ]

        for candidate in candidates:
            try:
                count = await candidate.count()
                for index in range(count):
                    item = candidate.nth(index)
                    if not await item.is_visible(timeout=500):
                        continue

                    await item.click(timeout=5000)
                    await page.wait_for_timeout(1200)

                    try:
                        await self.browser.handle_location_popup(page)
                    except Exception:
                        pass

                    mobile_input = await self._find_mobile_input(page)
                    if mobile_input is not None:
                        return mobile_input
            except Exception:
                continue

        header_controls = page.locator(
            "header button, "
            "header [role='button'], "
            "header a"
        )

        try:
            count = await header_controls.count()
            for index in range(count - 1, -1, -1):
                try:
                    item = header_controls.nth(index)
                    if not await item.is_visible(timeout=500):
                        continue

                    await item.click(timeout=5000)
                    await page.wait_for_timeout(1200)

                    try:
                        await self.browser.handle_location_popup(page)
                    except Exception:
                        pass

                    mobile_input = await self._find_mobile_input(page)
                    if mobile_input is not None:
                        return mobile_input
                except Exception:
                    continue
        except Exception:
            pass

        profile_selectors = [
            '[aria-label*="profile" i]',
            '[aria-label*="account" i]',
            '[aria-label*="login" i]',
            '[title*="profile" i]',
            '[title*="account" i]',
            '[title*="login" i]',
            'img[alt*="profile" i]',
            'img[alt*="avatar" i]',
            'img[alt*="account" i]',
        ]

        for selector in profile_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()

                for index in range(count):
                    item = locator.nth(index)
                    if not await item.is_visible(timeout=500):
                        continue

                    try:
                        await item.click(timeout=5000)
                    except Exception:
                        try:
                            await item.locator("..").click(timeout=3000)
                        except Exception:
                            continue

                    await page.wait_for_timeout(1200)

                    try:
                        await self.browser.handle_location_popup(page)
                    except Exception:
                        pass

                    mobile_input = await self._find_mobile_input(page)
                    if mobile_input is not None:
                        return mobile_input
            except Exception:
                continue

        return None

    # =========================================================
    # SEND OTP / CONTINUE
    # =========================================================

    async def _find_send_otp_button(self, page):
        candidates = [
            page.get_by_role("button", name="Continue", exact=True),
            page.get_by_text("Continue", exact=True),
            page.locator('button:has-text("Continue")'),
            page.get_by_role("button", name="Send OTP", exact=True),
            page.get_by_text("Send OTP", exact=True),
            page.locator('button:has-text("Send OTP")'),
        ]

        for locator in candidates:
            try:
                count = await locator.count()
                for index in range(count):
                    item = locator.nth(index)
                    if await item.is_visible(timeout=500):
                        return item
            except Exception:
                continue

        return None

    # =========================================================
    # OTP INPUTS
    # =========================================================

    async def _find_otp_inputs(self, page):
        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[inputmode="numeric"]',
            'input[placeholder*="OTP" i]',
            'input[placeholder*="code" i]',
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

        selectors = [
            'input[type="tel"]',
            'input[type="number"]',
        ]

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

        return found

    # =========================================================
    # VERIFY BUTTON
    # =========================================================

    async def _find_verify_button(self, page):
        candidates = [
            page.get_by_role("button", name="Verify Now", exact=True),
            page.get_by_text("Verify Now", exact=True),
            page.locator('button:has-text("Verify Now")'),
        ]

        for locator in candidates:
            try:
                count = await locator.count()
                for index in range(count):
                    item = locator.nth(index)
                    if await item.is_visible(timeout=500):
                        return item
            except Exception:
                continue

        return None

    # =========================================================
    # LOGIN
    # =========================================================

    async def handle_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args

        if len(args) < 2:
            await update.message.reply_text("❌ Format:\n/login S1-A1 9876543210")
            return

        slot_id = args[0].upper()
        phone_number = args[1].strip()

        try:
            account = self.get_account(slot_id)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {exc}")
            return

        if account.logged_in:
            await update.message.reply_text(f"⚠️ {slot_id} is already logged in.")
            return

        if not phone_number.isdigit() or len(phone_number) != 10:
            await update.message.reply_text("❌ Enter a valid 10-digit Indian mobile number.")
            return

        try:
            page = await self.browser.open_product_page(slot_id)

            try:
                await self.browser.handle_location_popup(page)
                await page.wait_for_timeout(1000)
            except Exception:
                pass

            account.update(
                phone_number=phone_number,
                active=True,
                current_page=page.url,
                last_error=None,
            )

            mobile_input = await self._open_login_popup(page)

            if mobile_input is None:
                screenshot_path = self.screenshots_dir / f"{slot_id}_login_profile_error.png"
                try:
                    await page.screenshot(path=str(screenshot_path), full_page=False)
                    account.update(last_screenshot=str(screenshot_path))
                    await self.telegram.send_photo(
                        photo_path=str(screenshot_path),
                        caption=(
                            "❌ LOGIN POPUP NOT OPENED\n\n"
                            f"Slot: {slot_id}\n"
                            "Expected: Wallet → Profile\n"
                            f"Page: {page.url}"
                        ),
                    )
                    if screenshot_path.exists():
                        screenshot_path.unlink()
                except Exception:
                    pass
                raise RuntimeError("Rooter Login popup could not be opened from the profile icon.")

            await mobile_input.fill(phone_number)
            await page.wait_for_timeout(500)

            send_otp_button = await self._find_send_otp_button(page)
            if send_otp_button is None:
                raise RuntimeError("Rooter Continue button was not found.")

            await send_otp_button.click(timeout=5000)
            otp_inputs = []

            for _ in range(30):
                await page.wait_for_timeout(500)
                otp_inputs = await self._find_otp_inputs(page)
                if otp_inputs:
                    break

            if not otp_inputs:
                raise RuntimeError("OTP verification popup did not appear.")

            account.update(
                current_page="otp_verification",
                last_error=None,
            )

            await update.message.reply_text(
                "📩 OTP sent successfully.\n\n"
                f"Slot: {slot_id}\n"
                f"Number: +91 {phone_number}\n\n"
                "OTP aane ke baad bhejo:\n"
                f"/otp {slot_id} 123456"
            )

        except Exception as exc:
            account.update(last_error=str(exc), active=False)
            await update.message.reply_text(
                "❌ Login start failed\n\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # OTP
    # =========================================================

    async def handle_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args

        if len(args) < 2:
            await update.message.reply_text("❌ Format:\n/otp S1-A1 123456")
            return

        slot_id = args[0].upper()
        otp = args[1].strip()

        try:
            account = self.get_account(slot_id)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {exc}")
            return

        if len(otp) != 6 or not otp.isdigit():
            await update.message.reply_text("❌ OTP must be exactly 6 digits.")
            return

        try:
            page = await self.browser.get_page(slot_id)
            await self.browser.handle_location_popup(page)

            otp_inputs = []
            for _ in range(20):
                otp_inputs = await self._find_otp_inputs(page)
                if otp_inputs:
                    break
                await page.wait_for_timeout(500)

            if not otp_inputs:
                raise RuntimeError("OTP input field was not found.")

            if len(otp_inputs) == 1:
                await otp_inputs[0].fill(otp)
            else:
                boxes = otp_inputs[:6]
                if len(boxes) < 6:
                    raise RuntimeError("OTP fields were found, but six OTP boxes are not available.")
                for index, digit in enumerate(otp):
                    await boxes[index].fill(digit)

            await page.wait_for_timeout(700)

            verify_button = await self._find_verify_button(page)
            if verify_button is None:
                raise RuntimeError("Verify Now button was not found.")

            await verify_button.click(timeout=5000)
            await page.wait_for_timeout(3500)
            await self.browser.handle_location_popup(page)
            await page.wait_for_timeout(1000)

            page = await self.browser.ensure_product_page(slot_id)
            await self.browser.handle_location_popup(page)
            await page.wait_for_timeout(1500)
            await self.browser.save_session(slot_id)

            account.update(
                logged_in=True,
                active=True,
                current_page=page.url,
                last_error=None,
            )

            screenshot_path = self.screenshots_dir / f"{slot_id}_login_success.png"
            await page.screenshot(path=str(screenshot_path), full_page=False)
            account.update(last_screenshot=str(screenshot_path))

            await self.telegram.send_photo(
                photo_path=str(screenshot_path),
                caption=(
                    "✅ LOGIN SUCCESSFUL\n\n"
                    f"Slot: {slot_id}\n"
                    f"Number: +91 {account.phone_number}\n"
                    "Session saved."
                ),
            )
            
            if screenshot_path.exists():
                screenshot_path.unlink()

            await update.message.reply_text(
                "✅ Login successful\n\n"
                f"Slot: {slot_id}\n"
                f"Number: +91 {account.phone_number}\n"
                "Session saved."
            )

        except Exception as exc:
            account.update(last_error=str(exc))
            await update.message.reply_text(
                "❌ OTP/Login failed\n\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # SCREENSHOT
    # =========================================================

    async def handle_screen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args

        if len(args) < 1:
            await update.message.reply_text("❌ Format:\n/screen S1-A1")
            return

        slot_id = args[0].upper()

        try:
            account = self.get_account(slot_id)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {exc}")
            return

        try:
            page = await self.browser.ensure_product_page(slot_id)
            await self.browser.handle_location_popup(page)
            await page.evaluate("window.scrollTo(0, 0)")

            screenshot_path = self.screenshots_dir / f"{slot_id}.png"
            await page.screenshot(path=str(screenshot_path), full_page=False)

            account.update(
                current_page=page.url,
                last_screenshot=str(screenshot_path),
                last_error=None,
            )

            await self.telegram.send_photo(
                photo_path=str(screenshot_path),
                caption=f"🖥 {slot_id}\nPage: {page.url}",
            )
            
            if screenshot_path.exists():
                screenshot_path.unlink()

        except Exception as exc:
            account.update(last_error=str(exc))
            await update.message.reply_text(
                "❌ Screenshot failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # REFRESH (UPDATED FOR WHITE SCREEN FIX)
    # =========================================================

    async def handle_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args

        if len(args) < 1:
            await update.message.reply_text("❌ Format:\n/refresh S1-A1")
            return

        slot_id = args[0].upper()

        try:
            account = self.get_account(slot_id)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {exc}")
            return

        try:
            page = await self.browser.get_page(slot_id)
            # Safe navigation jisse front-end react exceptions solve ho jayen
            await page.goto(settings.product_url, wait_until="domcontentloaded", timeout=60000)
            await self.browser.handle_location_popup(page)
            await page.wait_for_timeout(1500)
            await page.evaluate("window.scrollTo(0, 0)")

            account.update(current_page=page.url, last_error=None)

            await update.message.reply_text(
                "🔄 Refreshed Cleanly\n"
                f"Slot: {slot_id}\n"
                f"Page: {page.url}"
            )

        except Exception as exc:
            account.update(last_error=str(exc))
            await update.message.reply_text(
                "❌ Refresh failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # LOGOUT
    # =========================================================

    async def handle_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args

        if len(args) < 1:
            await update.message.reply_text("❌ Format:\n/logout S1-A1")
            return

        slot_id = args[0].upper()

        try:
            account = self.get_account(slot_id)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {exc}")
            return

        try:
            await self.browser.logout_slot(slot_id)

            account.update(
                phone_number=None,
                logged_in=False,
                active=False,
                current_page="unknown",
                last_error=None,
                last_screenshot=None,
                wallet_balance=None,
                last_order_id=None,
            )

            await update.message.reply_text(
                "🚪 Logged out\n\n"
                f"Slot: {slot_id}\n"
                "Session data cleared.\n"
                "Slot is ready for a new number."
            )

        except Exception as exc:
            account.update(last_error=str(exc))
            await update.message.reply_text(
                "❌ Logout failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # RECOVERY
    # =========================================================

    async def recover(self, slot_id: str, error_message: str):
        try:
            account = self.get_account(slot_id)
            account.update(last_error=error_message)
        except Exception:
            return

        screenshot_path = self.screenshots_dir / f"{slot_id}_error.png"

        try:
            page = await self.browser.get_page(slot_id)
            await page.screenshot(path=str(screenshot_path), full_page=False)
            account.update(last_screenshot=str(screenshot_path))

            await self.telegram.send_photo(
                photo_path=str(screenshot_path),
                caption=(
                    "⚠️ RECOVERY\n"
                    f"Slot: {slot_id}\n\n"
                    f"Error:\n{error_message}"
                ),
            )
            
            if screenshot_path.exists():
                screenshot_path.unlink()

        except Exception as screenshot_error:
            try:
                await self.telegram.send_message(
                    "⚠️ RECOVERY\n"
                    f"Slot: {slot_id}\n\n"
                    f"Error:\n{error_message}\n\n"
                    f"Screenshot error:\n{screenshot_error}"
                )
            except Exception:
                pass

        try:
            page = await self.browser.open_product_page(slot_id)
            await self.browser.handle_location_popup(page)
            account.update(current_page=page.url, last_error=None)
        except Exception as recovery_error:
            account.update(last_error=f"Recovery failed: {recovery_error}")
            try:
                await self.telegram.send_message(
                    "❌ Recovery failed\n"
                    f"Slot: {slot_id}\n"
                    f"Error: {recovery_error}"
                )
            except Exception:
                pass

    # =========================================================
    # 🎯 SNIPER BACKGROUND WORKER (CRASH FIX & CLEAN CLICK)
    # =========================================================
    async def _sniper_worker(self, slot_id: str):
        from datetime import datetime
        import asyncio
        account = self.get_account(slot_id)
        
        try:
            page = await self.browser.ensure_product_page(slot_id)
            await self.telegram.send_message(f"🎯 Sniper ACTIVATED for {slot_id}. Auto-refreshing every 2 mins...")

            while True:
                # 1. 2 Minute Wait ya Manual Trigger
                try:
                    await asyncio.wait_for(self.stock_event.wait(), timeout=120.0)
                    self.stock_event.clear() 
                except asyncio.TimeoutError:
                    pass
                
                account.update(current_page="CHECKING_STOCK")
                
                try:
                    # 2. Fresh Load to prevent React Client-Side Exceptions
                    await page.goto(settings.product_url, wait_until="domcontentloaded", timeout=30000)
                    await self.browser.handle_location_popup(page)
                    await page.wait_for_timeout(1000)

                    # Check if page is broken (White Screen)
                    content = await page.content()
                    if "Application error: a client-side exception" in content:
                        await self.telegram.send_message(f"⚠️ Website crashed for {slot_id}. Retrying in next loop...")
                        await asyncio.sleep(5)
                        continue
                    
                    # 3. Safe Click on 5000 Wallet Code
                    try:
                        rs_5000_option = page.locator("text=Rs.5000 Wallet Code").first
                        await rs_5000_option.wait_for(state="visible", timeout=8000)
                        # Normal click bina force ke taaki website break na ho
                        await rs_5000_option.click(timeout=3000)
                        await page.wait_for_timeout(1500)
                    except Exception:
                        pass # Ignore and continue if element not found this cycle
                    
                    # 4. Check karna ki Stock hai ya nahi (Pay via wallet button aana chahiye)
                    pay_btn_1 = page.get_by_role("button", name="Pay via wallet").first
                    is_in_stock = await pay_btn_1.is_visible(timeout=3000)
                    
                    if not is_in_stock:
                        # Out of stock hai, loop wapas 2 min wait par chala jayega
                        continue

                    # ==========================================
                    # 🚨 STOCK DETECTED - START BUY FLOW
                    # ==========================================
                    await self.telegram.send_message(f"🚨 STOCK DETECTED in {slot_id}! Starting auto-buy...")
                    
                    for target_qty in [2, 1]:
                        try:
                            # 1 Qty retry fresh load
                            if target_qty == 1:
                                await page.goto(settings.product_url, wait_until="domcontentloaded", timeout=30000)
                                await self.browser.handle_location_popup(page)
                                
                                try:
                                    rs_5000_option = page.locator("text=Rs.5000 Wallet Code").first
                                    await rs_5000_option.wait_for(state="visible", timeout=8000)
                                    await rs_5000_option.click(timeout=3000)
                                    await page.wait_for_timeout(1500)
                                except Exception:
                                    pass
                                
                                pay_btn_1 = page.get_by_role("button", name="Pay via wallet").first

                            # Qty 2 '+' click
                            if target_qty == 2:
                                try:
                                    plus_btn = page.locator("button:has-text('+')").first
                                    await plus_btn.wait_for(state="visible", timeout=3000)
                                    await plus_btn.click(timeout=2000)
                                    await page.wait_for_timeout(1500) 
                                except Exception:
                                    pass
                            
                            # Balance check
                            wallet_balance_text = "Balance info not found"
                            try:
                                balance_locator = page.locator("text=/Wallet Balance:/i").first
                                if await balance_locator.is_visible(timeout=3000):
                                    wallet_balance_text = await balance_locator.inner_text()
                            except Exception:
                                pass

                            # Screenshot
                            screenshot_path = self.screenshots_dir / f"{slot_id}_pre_buy_qty_{target_qty}.png"
                            await page.screenshot(path=str(screenshot_path), full_page=False)
                            
                            await self.telegram.send_photo(
                                photo_path=str(screenshot_path),
                                caption=(
                                    f"🛒 ATTEMPTING BUY (Qty {target_qty})!\n\n"
                                    f"Slot: {slot_id}\n"
                                    f"Balance Info: {wallet_balance_text}"
                                )
                            )
                            if screenshot_path.exists():
                                screenshot_path.unlink()

                            if "insufficient" in wallet_balance_text.lower() or "add money" in wallet_balance_text.lower():
                                await self.telegram.send_message(f"🚨 INSUFFICIENT BALANCE in {slot_id}. Buy stopped.")
                                break 
                                
                            # Payment flow
                            await pay_btn_1.wait_for(state="visible", timeout=5000)
                            await pay_btn_1.click(timeout=3000)

                            await page.locator("text=Delivery Details").wait_for(state="visible", timeout=6000)
                            await page.wait_for_timeout(1500)

                            pay_btn_2 = page.get_by_role("button", name="Pay via wallet").last
                            await pay_btn_2.wait_for(state="visible", timeout=5000)
                            await pay_btn_2.click(timeout=3000)

                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            await self.telegram.send_message(
                                f"✅✅ SUCCESS: CODE PURCHASED!\n\n"
                                f"Amount: Rs.5000\n"
                                f"Quantity: {target_qty}\n"
                                f"Slot: {slot_id}\n"
                                f"Time: {current_time}"
                            )
                            
                            break 

                        except Exception as e:
                            error_ss = self.screenshots_dir / f"{slot_id}_error_qty_{target_qty}.png"
                            try:
                                await page.screenshot(path=str(error_ss), full_page=False)
                                await self.telegram.send_photo(
                                    photo_path=str(error_ss),
                                    caption=f"⚠️ Failed to buy Qty {target_qty} for {slot_id}.\nError caught!"
                                )
                                if error_ss.exists():
                                    error_ss.unlink()
                            except Exception:
                                pass
                                
                            if target_qty == 2:
                                await self.telegram.send_message(f"🔄 {slot_id} retrying with Quantity 1...")
                            else:
                                await self.telegram.send_message(f"❌ {slot_id} failed completely.")

                    await self.telegram.send_message(f"⏳ {slot_id} purchase cycle complete. Resuming 2-min auto-refresh...")
                    await asyncio.sleep(10)
                    await page.goto(settings.product_url, wait_until="domcontentloaded")
                    await self.browser.handle_location_popup(page)
                    await asyncio.sleep(2) 

                except Exception as loop_err:
                    pass

        except Exception as e:
            await self.telegram.send_message(f"❌ Sniper worker critically crashed for {slot_id}: {str(e)}")
            self.sniper_tasks.pop(slot_id, None)

    # =========================================================
    # START / STOP SNIPER MODE
    # =========================================================
    async def handle_sniper_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if len(args) < 1:
            await update.message.reply_text("❌ Format: /sniper S1-A1 (or 'all')")
            return
            
        target = args[0].lower()

        if target == "all":
            started = 0
            for slot_id, acc in self.accounts.items():
                if acc.logged_in and slot_id not in self.sniper_tasks:
                    task = asyncio.create_task(self._sniper_worker(slot_id))
                    self.sniper_tasks[slot_id] = task
                    started += 1
            await update.message.reply_text(f"🔫 Sniper started for {started} active accounts!")
        else:
            slot_id = target.upper()
            try:
                acc = self.get_account(slot_id)
                if acc.logged_in and slot_id not in self.sniper_tasks:
                    task = asyncio.create_task(self._sniper_worker(slot_id))
                    self.sniper_tasks[slot_id] = task
                    await update.message.reply_text(f"🔫 Sniper started for {slot_id}")
                elif not acc.logged_in:
                    await update.message.reply_text(f"⚠️ {slot_id} is not logged in.")
                else:
                    await update.message.reply_text(f"⚠️ Sniper already running for {slot_id}.")
            except ValueError as exc:
                await update.message.reply_text(f"❌ {exc}")

    # =========================================================
    # FIRE THE SNIPERS
    # =========================================================
    async def trigger_stock_buy(self):
        self.stock_event.set()
        await asyncio.sleep(3)
        self.stock_event.clear()

    async def handle_trigger_buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🚨 MANUAL TRIGGER SENT! All snipers firing!")
        await self.trigger_stock_buy()
