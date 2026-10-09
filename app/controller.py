import asyncio
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
        self.telegram.register_command("sniper", self.handle_sniper_mode)
        self.telegram.register_command("trigger_buy", self.handle_trigger_buy)

    # =========================================================
    # START / HELP
    # =========================================================

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Rooter Auto Buyer (God Mode 30s)\n\n"
            f"Total slots: {settings.total_slots}\n"
            f"Current Service ID: {settings.current_service_id}\n"
            f"Accounts/service: {settings.accounts_per_service}\n\n"
            "System Online & Stable. Use /status to monitor."
        )

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📖 Commands\n\n"
            "/start\n/status\n/login S1-A1 9876543210\n/otp S1-A1 123456\n"
            "/screen S1-A1\n/refresh S1-A1\n/logout S1-A1\n/sniper all\n/trigger_buy\n/help"
        )

    # =========================================================
    # STATUS (ADVANCED TELEMETRY)
    # =========================================================

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lines = ["📊 LIVE ACCOUNT STATUS", ""]

        for account in self.all_accounts():
            phone = account.phone_number if account.phone_number else "-"
            login_state = "✅ LOGGED IN" if account.logged_in else "❌ NOT LOGGED IN"
            sniper_state = "🔫 SNIPER: ON" if account.slot_id in self.sniper_tasks else "🔫 SNIPER: OFF"
            balance = f"₹{account.wallet_balance:.2f}" if account.wallet_balance is not None else "-"

            lines.append(f"🆔 {account.slot_id} | {login_state} | {sniper_state}")
            if phone != "-":
                lines.append(f"  📱 Num: {phone} | Bal: {balance}")
            
            lines.append(f"  📍 State: {account.current_page}")

            if account.last_error:
                lines.append(f"  ⚠️ Error: {account.last_error}")
            
            lines.append("") 

        await update.message.reply_text("\n".join(lines))

    # =========================================================
    # LOGIN / OTP HELPER LOCATORS
    # =========================================================

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
                        if ph and "search" in ph.lower(): continue
                        return item
            except Exception: pass
        return None

    async def _open_login_popup(self, page):
        try: await self.browser.handle_location_popup(page)
        except Exception: pass
        await page.wait_for_timeout(1000)

        mobile_input = await self._find_mobile_input(page)
        if mobile_input is not None: return mobile_input

        try:
            await page.evaluate('''() => {
                const header = document.querySelector('header');
                if(header) {
                    const elements = Array.from(header.querySelectorAll('svg, button, img, .mantine-Avatar-root'));
                    if(elements.length > 0) {
                        const profileIcon = elements[elements.length - 1];
                        profileIcon.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        profileIcon.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        profileIcon.click();
                    }
                }
            }''')
            await page.wait_for_timeout(2000)
            mobile_input = await self._find_mobile_input(page)
            if mobile_input: return mobile_input
        except Exception: pass

        candidates = [page.get_by_text("Login / Sign Up", exact=True), page.get_by_text("Login", exact=True)]
        for candidate in candidates:
            try:
                if await candidate.count() > 0 and await candidate.first.is_visible(timeout=300):
                    await candidate.first.click(force=True, timeout=2000)
                    await page.wait_for_timeout(1500)
                    mobile_input = await self._find_mobile_input(page)
                    if mobile_input: return mobile_input
            except Exception: pass

        return None

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
            except Exception: pass
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
                    if await item.is_visible(timeout=300): found.append(item)
                if found: return found
            except Exception: continue
                
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
                if len(found) >= 6: return found[:8] 
            except Exception: pass
                
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
            except Exception: pass
        return None

    # =========================================================
    # LOGIN & OTP & SCREEN & LOGOUT
    # =========================================================

    async def handle_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            if len(args) < 2: return await update.message.reply_text("❌ Format:\n/login S1-A1 9876543210")
            slot_id, phone_number = args[0].upper(), args[1].strip()
            
            account = self.get_account(slot_id)
            if account.logged_in: return await update.message.reply_text(f"⚠️ {slot_id} is already logged in.")
            if not phone_number.isdigit() or len(phone_number) != 10:
                return await update.message.reply_text("❌ Enter a valid 10-digit Indian mobile number.")

            await update.message.reply_text(f"🔍 Ensuring product page for {slot_id}...")
            
            page = await self.browser.open_product_page(slot_id)
            await page.goto(settings.product_url, wait_until="domcontentloaded", timeout=60000)
            
            try: await self.browser.handle_location_popup(page); await page.wait_for_timeout(2000)
            except Exception: pass

            account.update(phone_number=phone_number, active=True, current_page="🔐 Handling Login", last_error=None)
            
            mobile_input = await self._open_login_popup(page)
            if mobile_input is None: 
                screenshot_path = self.screenshots_dir / f"{slot_id}_login_error.png"
                await page.screenshot(path=str(screenshot_path), full_page=False)
                await self.telegram.send_photo(photo_path=str(screenshot_path), caption=f"❌ Login popup not opened.")
                if screenshot_path.exists(): screenshot_path.unlink()
                raise RuntimeError("Login popup not opened.")
            
            await mobile_input.focus()
            await page.keyboard.type(phone_number, delay=50)
            await page.wait_for_timeout(1000)

            send_otp_button = await self._find_send_otp_button(page)
            if send_otp_button is None: 
                error_ss = self.screenshots_dir / f"{slot_id}_continue_btn_err.png"
                await page.screenshot(path=str(error_ss), full_page=False)
                await self.telegram.send_photo(photo_path=str(error_ss), caption=f"❌ Continue button not found.")
                if error_ss.exists(): error_ss.unlink()
                raise RuntimeError("Continue button not found.")
            
            await send_otp_button.evaluate("(el) => { el.removeAttribute('disabled'); el.removeAttribute('data-disabled'); el.disabled = false; }")
            await send_otp_button.click(force=True, timeout=3000)

            for _ in range(40): 
                await page.wait_for_timeout(500)
                if await self._find_otp_inputs(page): break
            else: 
                error_ss = self.screenshots_dir / f"{slot_id}_otp_popup_err.png"
                await page.screenshot(path=str(error_ss), full_page=False)
                await self.telegram.send_photo(photo_path=str(error_ss), caption=f"❌ OTP popup didn't appear.")
                if error_ss.exists(): error_ss.unlink()
                raise RuntimeError("OTP popup did not appear.")

            account.update(current_page="📩 OTP Sent. Waiting...", last_error=None)
            await update.message.reply_text(f"📩 OTP sent for {slot_id}.\nSend: /otp {slot_id} 123456")
        except Exception as exc:
            try: account.update(last_error=str(exc), active=False)
            except: pass
            await update.message.reply_text(f"❌ Login start failed: {exc}")

    async def handle_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            if len(args) < 2: return await update.message.reply_text("❌ Format:\n/otp S1-A1 123456")
            slot_id, otp = args[0].upper(), args[1].strip()
            
            account = self.get_account(slot_id)
            if len(otp) not in [6, 8] or not otp.isdigit():
                return await update.message.reply_text("❌ OTP must be exactly 6 or 8 digits.")

            page = await self.browser.get_page(slot_id)
            
            otp_inputs = []
            for attempt in range(20):
                otp_inputs = await self._find_otp_inputs(page)
                if otp_inputs and (len(otp_inputs) == 1 or len(otp_inputs) >= len(otp)):
                    break
                await page.wait_for_timeout(500)
                
            if not otp_inputs: 
                raise RuntimeError("OTP fields not found on the page.")

            if len(otp_inputs) == 1: 
                await otp_inputs[0].focus()
                await page.keyboard.type(otp, delay=50)
            else:
                boxes = otp_inputs[:len(otp)]
                for i, digit in enumerate(otp):
                    if i < len(boxes):
                        await boxes[i].focus()
                        await page.keyboard.press(digit)
                        await page.wait_for_timeout(50)

            await page.wait_for_timeout(1000) 
            
            verify_button = await self._find_verify_button(page)
            if verify_button is None: 
                raise RuntimeError("Verify button not found.")
                
            await verify_button.evaluate("(el) => { el.removeAttribute('disabled'); el.removeAttribute('data-disabled'); el.disabled = false; }")
            await verify_button.click(force=True, timeout=3000)
            await page.wait_for_timeout(3500)

            page = await self.browser.ensure_product_page(slot_id)
            await self.browser.save_session(slot_id)
            account.update(logged_in=True, active=True, current_page="✅ Logged In Idle", last_error=None)
            await update.message.reply_text(f"✅ Login successful for {slot_id}.")
            
            # 🔥 NEW: AUTO-START SNIPER AFTER LOGIN 🔥
            if slot_id not in self.sniper_tasks:
                self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))
                await update.message.reply_text(f"🔫 Sniper AUTO-STARTED for {slot_id}!")
                
        except Exception as exc:
            try: account.update(last_error=str(exc))
            except: pass
            await update.message.reply_text(f"❌ OTP failed: {exc}")

    async def handle_screen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args: return await update.message.reply_text("❌ Format:\n/screen S1-A1")
            slot_id = context.args[0].upper()
            account = self.get_account(slot_id)

            page = await self.browser.ensure_product_page(slot_id)
            screenshot_path = self.screenshots_dir / f"{slot_id}.png"
            await page.screenshot(path=str(screenshot_path), full_page=False)
            account.update(current_page=page.url)
            await self.telegram.send_photo(photo_path=str(screenshot_path), caption=f"🖥 {slot_id}\nPage: {page.url}")
            if screenshot_path.exists(): screenshot_path.unlink()
        except Exception as exc:
            try: account.update(last_error=str(exc))
            except: pass
            await update.message.reply_text(f"❌ Screenshot failed: {exc}")

    async def handle_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args: return await update.message.reply_text("❌ Format:\n/refresh S1-A1")
            slot_id = context.args[0].upper()
            account = self.get_account(slot_id)

            page = await self.browser.get_page(slot_id)
            cb = int(time.time())
            fresh_url = f"{settings.product_url}?cb={cb}" if "?" not in settings.product_url else f"{settings.product_url}&cb={cb}"
            await page.goto(fresh_url, wait_until="domcontentloaded", timeout=60000)
            
            # Ensure bot knows it's logged in (in case of container restart)
            account.update(logged_in=True, current_page="🔄 Manually Refreshed", last_error=None)
            await update.message.reply_text(f"🔄 Hard Refreshed {slot_id}")
            
            # 🔥 NEW: AUTO-START SNIPER ON REFRESH 🔥
            if slot_id not in self.sniper_tasks:
                self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))
                await update.message.reply_text(f"🔫 Sniper AUTO-STARTED for {slot_id} via refresh!")

        except Exception as exc:
            try: account.update(last_error=str(exc))
            except: pass
            await update.message.reply_text(f"❌ Refresh failed: {exc}")

    async def handle_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args: return await update.message.reply_text("❌ Format:\n/logout S1-A1")
            slot_id = context.args[0].upper()
            account = self.get_account(slot_id)
            await self.browser.logout_slot(slot_id)
            account.update(phone_number=None, logged_in=False, active=False, current_page="unknown", last_error=None, wallet_balance=None)
            await update.message.reply_text(f"🚪 Logged out {slot_id}")
        except Exception as exc:
            await update.message.reply_text(f"❌ Logout failed: {exc}")


    # =========================================================
    # 🎯 30s SNIPER BACKGROUND WORKER (GOD MODE)
    # =========================================================
    async def _sniper_worker(self, slot_id: str):
        account = self.get_account(slot_id)
        
        try:
            page = await self.browser.ensure_product_page(slot_id)
            await self.telegram.send_message(f"🎯 Sniper ACTIVATED for {slot_id}. 30-sec Auto-Refresh running...")

            while True:
                try:
                    account.update(last_error=None)

                    # 1. 30-SECOND WAIT PHASE WITH TIMESTAMP 🔥
                    last_time = datetime.now().strftime("%I:%M:%S %p")
                    account.update(current_page=f"⏳ [STAGE: 30s Wait] (Last Checked: {last_time})")
                    
                    try:
                        await asyncio.wait_for(self.stock_event.wait(), timeout=30.0)
                        self.stock_event.clear() 
                        account.update(current_page="⚡ [STAGE: Manual Trigger Received]")
                    except asyncio.TimeoutError:
                        pass
                    
                    # 2. ANTI-CACHE HARD REFRESH
                    account.update(current_page="🔄 [STAGE: Hard Refreshing Page]")
                    cache_buster = int(time.time())
                    fresh_url = f"{settings.product_url}?cb={cache_buster}" if "?" not in settings.product_url else f"{settings.product_url}&cb={cache_buster}"
                    
                    await page.goto(fresh_url, wait_until="domcontentloaded", timeout=30000)
                    try: await self.browser.handle_location_popup(page)
                    except: pass
                    await page.wait_for_timeout(2000) 

                    content = await page.content()
                    if "Application error: a client-side exception" in content:
                        account.update(last_error="Website Crashed (White Screen)")
                        await asyncio.sleep(5)
                        continue
                    
                    # 3. AGGRESSIVE 5000 SELECTION
                    account.update(current_page="🎯 [STAGE: Selecting Rs.5000]")
                    rs_5000_locator = page.locator("text=Rs.5000 Wallet Code >> visible=true")
                    
                    if await rs_5000_locator.count() > 0:
                        try:
                            await rs_5000_locator.first.click(force=True, timeout=3000)
                            await rs_5000_locator.first.evaluate("(el) => { if(el.parentElement) el.parentElement.click(); }")
                        except Exception as click_err:
                            account.update(last_error=f"Selection Click Error: {str(click_err)[:50]}")
                    else:
                        fallback_loc = page.locator("text=5000 >> visible=true")
                        if await fallback_loc.count() > 0:
                            try:
                                await fallback_loc.last.click(force=True, timeout=3000)
                                await fallback_loc.last.evaluate("(el) => { if(el.parentElement) el.parentElement.click(); }")
                            except Exception as click_err:
                                account.update(last_error=f"Fallback Selection Error: {str(click_err)[:50]}")
                        else:
                            account.update(last_error="Rs.5000 element completely missing from DOM")
                            
                    await page.wait_for_timeout(1500) 
                    
                    # 4. STOCK CHECK RADAR
                    account.update(current_page="🔍 [STAGE: Checking for Pay Button]")
                    pay_btn_1 = page.locator("button >> text='Pay via wallet' >> visible=true").first
                    is_in_stock = False
                    try: is_in_stock = await pay_btn_1.is_visible(timeout=3000)
                    except: pass
                    
                    if not is_in_stock:
                        # Thoda ruk kar update dikhayega taaki tu padh sake
                        account.update(current_page="😴 [STAGE: Out of Stock, Looping]")
                        await asyncio.sleep(2) 
                        continue

                    # ==========================================
                    # 🚨 STOCK DETECTED - EXECUTE BUY FLOW
                    # ==========================================
                    account.update(current_page="🚨 [STAGE: INITIATING BUY FLOW!]")
                    await self.telegram.send_message(f"🚨 STOCK DETECTED in {slot_id}! Starting auto-buy...")
                    
                    for target_qty in [2, 1]:
                        try:
                            if target_qty == 1:
                                account.update(current_page="🔄 [STAGE: Retrying with Qty 1]")
                                retry_url = f"{settings.product_url}?retry={int(time.time())}" if "?" not in settings.product_url else f"{settings.product_url}&retry={int(time.time())}"
                                await page.goto(retry_url, wait_until="domcontentloaded", timeout=30000)
                                await page.wait_for_timeout(2000)
                                
                                rs_5000_loc = page.locator("text=Rs.5000 Wallet Code >> visible=true")
                                if await rs_5000_loc.count() > 0:
                                    await rs_5000_loc.first.click(force=True)
                                    await rs_5000_loc.first.evaluate("(el) => { if(el.parentElement) el.parentElement.click(); }")
                                    await page.wait_for_timeout(1500)
                                
                                pay_btn_1 = page.locator("button >> text='Pay via wallet' >> visible=true").first

                            if target_qty == 2:
                                account.update(current_page="➕ [STAGE: Changing Quantity to 2]")
                                try:
                                    plus_btn = page.locator("button:has-text('+') >> visible=true").first
                                    await plus_btn.wait_for(state="visible", timeout=3000)
                                    await plus_btn.click(force=True, timeout=2000)
                                    await plus_btn.evaluate("(el) => el.click()")
                                    await page.wait_for_timeout(1500) 
                                except Exception as e:
                                    account.update(last_error=f"Plus Button Error: {str(e)[:50]}")
                            
                            account.update(current_page="💰 [STAGE: Checking Balance]")
                            wallet_balance_text = "Balance info not found"
                            try:
                                balance_locator = page.locator("text=/Wallet Balance:/i >> visible=true").first
                                if await balance_locator.is_visible(timeout=2000):
                                    wallet_balance_text = await balance_locator.inner_text()
                            except Exception: pass

                            account.update(current_page="📸 [STAGE: Taking Verification Screenshot]")
                            screenshot_path = self.screenshots_dir / f"{slot_id}_pre_buy_qty_{target_qty}.png"
                            try:
                                await page.screenshot(path=str(screenshot_path), full_page=False)
                                await self.telegram.send_photo(
                                    photo_path=str(screenshot_path),
                                    caption=(f"🛒 ATTEMPTING BUY (Qty {target_qty})!\n\nSlot: {slot_id}\nBalance Info: {wallet_balance_text}")
                                )
                                if screenshot_path.exists(): screenshot_path.unlink()
                            except: pass

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
                            await page.wait_for_timeout(1500)

                            account.update(current_page="💳 [STAGE: Clicking Final Pay Button]")
                            pay_btn_2 = page.locator("button >> text='Pay via wallet' >> visible=true").last
                            await pay_btn_2.wait_for(state="visible", timeout=5000)
                            await pay_btn_2.click(force=True, timeout=3000)
                            await pay_btn_2.evaluate("(el) => el.click()")

                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            account.update(current_page="✅ [STAGE: SUCCESS - Code Bought!]")
                            await self.telegram.send_message(f"✅✅ SUCCESS: CODE PURCHASED!\nAmount: Rs.5000\nQty: {target_qty}\nSlot: {slot_id}\nTime: {current_time}")
                            break 

                        except Exception as flow_err:
                            account.update(last_error=f"Buy Flow Qty {target_qty} Error: {str(flow_err)[:60]}")
                            error_ss = self.screenshots_dir / f"{slot_id}_error_qty_{target_qty}.png"
                            try:
                                await page.screenshot(path=str(error_ss), full_page=False)
                                await self.telegram.send_photo(photo_path=str(error_ss), caption=f"⚠️ Failed Qty {target_qty} for {slot_id}")
                                if error_ss.exists(): error_ss.unlink()
                            except Exception: pass
                                
                            if target_qty == 2:
                                await self.telegram.send_message(f"🔄 {slot_id} retrying with Quantity 1...")
                            else:
                                account.update(current_page="❌ [STAGE: Buy Flow Failed Completely]")
                                await self.telegram.send_message(f"❌ {slot_id} failed completely.")

                    await asyncio.sleep(5)
                    
                except Exception as loop_err:
                    account.update(last_error=f"Outer Loop Error: {str(loop_err)[:80]}")
                    await page.wait_for_timeout(2000)

        except Exception as e:
            account.update(current_page="☠️ FATAL CRASH")
            await self.telegram.send_message(f"❌ Sniper worker critically crashed for {slot_id}: {str(e)}")
            self.sniper_tasks.pop(slot_id, None)


    # =========================================================
    # START / STOP SNIPER & MANUAL TRIGGER
    # =========================================================
    
    async def handle_sniper_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
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
                except ValueError as exc:
                    await update.message.reply_text(f"❌ {exc}")
        except Exception as exc:
            pass

    async def trigger_stock_buy(self):
        self.stock_event.set()
        await asyncio.sleep(3)
        self.stock_event.clear()

    async def handle_trigger_buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🚨 MANUAL TRIGGER SENT! All snipers bypassing wait timer!")
        await self.trigger_stock_buy()
