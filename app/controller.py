import asyncio
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from .browser import BrowserManager
from .config import settings
from .state import AccountState
from .telegram import TelegramBot

# Force real-time logs on Railway Deploy Logs
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


def log_step(slot_id: str, msg: str):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] [{slot_id}] {msg}", flush=True)


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
        log_step("SYSTEM", f"Controller initialized for Service ID {settings.current_service_id}")

    # =========================================================
    # SLOT MANAGEMENT & AUTO SESSION RESTORE
    # =========================================================

    def _create_slots(self):
        service_number = settings.current_service_id
        for account_number in range(1, settings.accounts_per_service + 1):
            slot_id = f"S{service_number}-A{account_number}"
            state = AccountState(slot_id=slot_id)

            try:
                session_dir = self.browser.sessions.session_path(slot_id)
                storage_file = session_dir / "storage_state.json"
                if storage_file.exists() and storage_file.stat().st_size > 10:
                    saved_phone = self.browser.load_saved_phone(slot_id)
                    state.logged_in = True
                    state.active = True
                    state.phone_number = saved_phone or "Saved Session"
                    state.current_page = "✅ Session Restored (Auto-Starting...)"
                    log_step(slot_id, f"Restored saved session (ID: {state.phone_number})")
            except Exception as e:
                log_step(slot_id, f"Session restore note: {e}")

            self.accounts[slot_id] = state

    def _ensure_snipers_running(self) -> int:
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
        self.telegram.register_command("cookie", self.handle_cookie_import)
        self.telegram.register_command("popup", self.handle_force_popup)
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
            "/login S1-A1 9876543210 - Human Login with Phone\n"
            "/otp S1-A1 123456 - Submit OTP\n"
            "/cookie S1-A1 <token> - Instant Token Login (Auto-Reloads Browser)\n"
            "/popup S1-A1 - Force click 'No, stay on this site'\n"
            "/screen S1-A1 - Live page screenshot\n"
            "/refresh S1-A1 - Hard refresh & start sniper\n"
            "/trigger_buy - Wake up ALL accounts & attack stock NOW\n"
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
                lines.append(f"  📱 ID/Num: {phone} | Bal: {balance}")

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
    # INSTANT COOKIE / SHORT TOKEN IMPORT (WITH LIVE RELOAD)
    # =========================================================

    def _normalize_cookie_for_playwright(self, c: dict) -> dict:
        exp = c.get("expirationDate") or c.get("expires") or 1893456000
        same_site_raw = str(c.get("sameSite") or "Lax").lower()
        if "strict" in same_site_raw:
            same_site = "Strict"
        elif "none" in same_site_raw or "no_restriction" in same_site_raw:
            same_site = "None"
        else:
            same_site = "Lax"

        return {
            "name": str(c["name"]),
            "value": str(c["value"]),
            "domain": str(c.get("domain", ".rooter.gg")),
            "path": str(c.get("path", "/")),
            "expires": float(exp),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True if same_site == "None" else False)),
            "sameSite": same_site,
        }

    async def handle_cookie_import(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            slot_id = ""
            raw_input = ""

            # Case 1: Uploaded .json file
            if update.message and update.message.document:
                if context.args:
                    slot_id = context.args[0].upper()
                elif update.message.caption:
                    for part in update.message.caption.upper().split():
                        if "-A" in part:
                            slot_id = part
                            break
                if not slot_id:
                    return await update.message.reply_text("❌ Caption mein `/cookie S1-A1` likh kar file bhej bhai!")

                tg_file = await context.bot.get_file(update.message.document.file_id)
                file_bytes = await tg_file.download_as_bytearray()
                raw_input = file_bytes.decode("utf-8").strip()
            else:
                # Case 2: Text command (/cookie S1-A1 <token_or_json>)
                if not context.args or len(context.args) < 2:
                    return await update.message.reply_text(
                        "❌ Format:\n`/cookie S1-A1 <user_auth_value>`\n"
                        "Ya fir `.json` file attach karke caption mein `/cookie S1-A1` likh!"
                    )
                slot_id = context.args[0].upper()
                raw_input = " ".join(context.args[1:]).strip()

            account = self.get_account(slot_id)
            await update.message.reply_text(f"⏳ Injecting session & Indian region cookies into {slot_id}...")

            # Pause existing sniper while resetting context
            old_task = self.sniper_tasks.pop(slot_id, None)
            if old_task and not old_task.done():
                old_task.cancel()

            exp = 1893456000
            playwright_cookies = list(self.browser.get_indian_region_cookies())
            user_label = "Token-Auth"

            # Check if full JSON array or short user_auth token
            if raw_input.startswith("["):
                parsed_list = json.loads(raw_input)
                for item in parsed_list:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        playwright_cookies.append(self._normalize_cookie_for_playwright(item))
                        if item["name"] == "user_auth":
                            try:
                                dec = urllib.parse.unquote(item["value"])
                                uid = json.loads(dec).get("userId")
                                if uid:
                                    user_label = f"UID:{uid}"
                            except Exception:
                                pass
            else:
                token_value = raw_input.strip().strip('"').strip("'")
                # Agar user ne decoded JSON diya ho toh URL-encode kar do
                if token_value.startswith("{"):
                    try:
                        uid = json.loads(token_value).get("userId")
                        if uid:
                            user_label = f"UID:{uid}"
                    except Exception:
                        pass
                    token_value = urllib.parse.quote(token_value, safe="")
                else:
                    try:
                        dec = urllib.parse.unquote(token_value)
                        uid = json.loads(dec).get("userId")
                        if uid:
                            user_label = f"UID:{uid}"
                    except Exception:
                        pass

                playwright_cookies.extend([
                    {
                        "name": "user_auth",
                        "value": token_value,
                        "domain": ".rooter.gg",
                        "path": "/",
                        "expires": exp,
                        "httpOnly": False,
                        "secure": True,
                        "sameSite": "Lax",
                    },
                    {
                        "name": "client_id",
                        "value": "08c76d30-cf1b-11f1-bb91-a7a0572fd2db",
                        "domain": ".rooter.gg",
                        "path": "/",
                        "expires": exp,
                        "httpOnly": False,
                        "secure": True,
                        "sameSite": "Lax",
                    },
                ])

            # 1. Purana browser context band karo taaki naya storage_state 100% load ho
            await self.browser.close_slot(slot_id)

            # 2. Disk par storage_state.json write karo
            session_dir = self.browser.sessions.session_path(slot_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            storage_file = session_dir / "storage_state.json"
            storage_file.write_text(json.dumps({"cookies": playwright_cookies, "origins": []}))

            # 3. Naya context open karke product page load karo aur session save karo
            page = await self.browser.open_product_page(slot_id)
            await self._destroy_location_popup(page, slot_id)
            balance_txt = await self._update_live_balance(page, account)
            await self.browser.save_session(slot_id, user_label)

            account.update(
                phone_number=user_label,
                logged_in=True,
                active=True,
                current_page="✅ Token Active & Verified",
                last_error=None,
            )
            log_step(slot_id, f"Cookie session live-loaded ({user_label}) | {balance_txt}")

            # 4. Auto-start Sniper
            self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))

            await update.message.reply_text(
                f"✅ Success! {slot_id} Live Logged-In ({user_label})!\n"
                f"💰 Wallet: {balance_txt}\n"
                f"🔫 Swarm Sniper Auto-Started! Ab `/screen {slot_id}` bhej kar dekh le!"
            )
        except Exception as exc:
            log_step("COOKIE_ERR", f"Failed: {exc}")
            await update.message.reply_text(f"❌ Cookie import failed: {exc}")

    # =========================================================
    # MANUAL & AUTO LOCATION POPUP HANDLER
    # =========================================================

    async def handle_force_popup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args:
                return await update.message.reply_text("❌ Format:\n/popup S1-A1")
            slot_id = context.args[0].upper()

            page = await self.browser.get_page(slot_id)
            if not page.url or page.url == "about:blank":
                return await update.message.reply_text(f"❌ {slot_id} ka browser page active nahi hai.")

            await self._destroy_location_popup(page, slot_id)
            await self.browser.save_session(slot_id, self.get_account(slot_id).phone_number)

            await update.message.reply_text(
                f"✅ 'No, stay on this site' clicked & Indian region locked for {slot_id}!\n"
                f"Ab `/screen {slot_id}` check kar."
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ Force popup failed: {exc}")

    async def _destroy_location_popup(self, page, slot_id: str = "SLOT"):
        """
        Real Human Click + Indian Cookie Lock taaki popup click hokar hamesha ke liye band ho.
        """
        try:
            await self.browser.handle_location_popup(page, slot_id)
        except Exception:
            pass

        try:
            curr_url = (page.url or "").lower()
            if curr_url and "playstation" not in curr_url and "about:blank" not in curr_url:
                log_step(slot_id, f"Redirected to {curr_url}! Returning to PlayStation product page...")
                await page.goto(settings.product_url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(1.2)
                await self.browser.handle_location_popup(page, slot_id)
        except Exception as e:
            log_step(slot_id, f"URL check note: {e}")

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

    # =========================================================
    # HUMAN LOGIN & OTP HELPERS
    # =========================================================

    async def _find_mobile_input(self, page):
        selectors = [
            'input[type="tel"]',
            'input[inputmode="tel"]',
            'input[name="phone"]',
            'input[placeholder*="mobile" i]',
            'input[placeholder*="number" i]',
            'input[placeholder*="phone" i]',
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    item = locator.nth(index)
                    if await item.is_visible(timeout=300):
                        box = await item.bounding_box()
                        if box and box["y"] < 85:
                            continue
                        ph = (await item.get_attribute("placeholder") or "").lower()
                        if "search" in ph or "bgmi" in ph or "valorant" in ph:
                            continue
                        return item
            except Exception:
                pass
        return None

    async def _open_login_popup(self, page, slot_id: str = "SLOT"):
        await self._destroy_location_popup(page, slot_id)
        await asyncio.sleep(0.6)

        mobile_input = await self._find_mobile_input(page)
        if mobile_input is not None:
            return mobile_input

        try:
            icon_info = await page.evaluate("""() => {
                const svgs = Array.from(document.querySelectorAll('svg, button, a'));
                const topRight = [];
                for (const el of svgs) {
                    const r = el.getBoundingClientRect();
                    if (r.top >= 5 && r.top <= 80 && r.left > 900 && r.width >= 12 && r.width <= 70) {
                        topRight.push({
                            x: r.left + r.width / 2,
                            y: r.top + r.height / 2,
                            left: r.left
                        });
                    }
                }
                if (topRight.length === 0) return null;
                topRight.sort((a, b) => b.left - a.left);
                return topRight[0];
            }""")

            if icon_info and "x" in icon_info and "y" in icon_info:
                px, py = icon_info["x"], icon_info["y"]
                await page.mouse.move(px, py, steps=6)
                await page.mouse.click(px, py)
                await asyncio.sleep(1.8)
                mobile_input = await self._find_mobile_input(page)
                if mobile_input is not None:
                    return mobile_input
        except Exception:
            pass

        # Fallback coordinates for 1280x720 top-right profile icon
        for coord_x in [1208, 1145, 1225]:
            try:
                await page.mouse.move(coord_x, 36, steps=5)
                await page.mouse.click(coord_x, 36)
                await asyncio.sleep(1.5)
                mobile_input = await self._find_mobile_input(page)
                if mobile_input is not None:
                    return mobile_input
            except Exception:
                pass

        candidates = [
            page.get_by_text("Login / Sign Up", exact=False),
            page.get_by_text("Login", exact=True),
        ]
        for candidate in candidates:
            try:
                if await candidate.count() > 0 and await candidate.first.is_visible(timeout=300):
                    await candidate.first.click(force=True, timeout=2000)
                    await asyncio.sleep(1.5)
                    mobile_input = await self._find_mobile_input(page)
                    if mobile_input:
                        return mobile_input
            except Exception:
                pass

        return None

    async def _find_send_otp_button(self, page):
        candidates = [
            page.locator("button:has-text('Continue')"),
            page.locator("button:has-text('CONTINUE')"),
            page.locator("button:has-text('Send OTP')"),
            page.locator("button:has-text('Get OTP')"),
        ]
        for locator in candidates:
            try:
                count = await locator.count()
                for i in range(count):
                    btn = locator.nth(i)
                    if await btn.is_visible(timeout=300):
                        txt = (await btn.inner_text() or "").strip().lower()
                        if "switch" in txt or "local" in txt or "stay" in txt or "yes" in txt:
                            continue
                        return btn
            except Exception:
                pass
        return None

    async def _find_otp_inputs(self, page, phone_number: str = ""):
        try:
            inputs = page.locator("input:visible")
            count = await inputs.count()
            valid_boxes = []

            for i in range(count):
                el = inputs.nth(i)
                box = await el.bounding_box()
                if not box or box["y"] < 85:
                    continue

                ph = (await el.get_attribute("placeholder") or "").lower()
                if "search" in ph or "bgmi" in ph or "valorant" in ph or "mobile" in ph or "phone" in ph:
                    continue

                val = (await el.input_value() or "").strip()
                if phone_number and phone_number in val:
                    continue

                valid_boxes.append(el)

            if len(valid_boxes) >= 4:
                return valid_boxes[:8]

            if len(valid_boxes) == 1:
                verify_btn = await self._find_verify_button(page)
                if verify_btn is not None:
                    return valid_boxes
        except Exception:
            pass

        return []

    async def _find_verify_button(self, page):
        candidates = [
            page.locator("button:has-text('Verify')"),
            page.locator("button:has-text('VERIFY')"),
            page.get_by_role("button", name="Verify Now", exact=False),
        ]
        for locator in candidates:
            try:
                count = await locator.count()
                for i in range(count):
                    btn = locator.nth(i)
                    if await btn.is_visible(timeout=300):
                        return btn
            except Exception:
                pass
        return None

    # =========================================================
    # LOGIN & OTP & SCREEN & LOGOUT
    # =========================================================

    async def handle_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        slot_id = "UNKNOWN"
        try:
            args = context.args
            if not args or len(args) < 2:
                return await update.message.reply_text("❌ Format:\n/login S1-A1 9876543210")
            slot_id, phone_number = args[0].upper(), args[1].strip()

            account = self.get_account(slot_id)
            if account.logged_in:
                return await update.message.reply_text(
                    f"⚠️ {slot_id} pehle se logged in hai. Naya login karne ke liye pehle `/logout {slot_id}` bhej."
                )
            if not phone_number.isdigit() or len(phone_number) != 10:
                return await update.message.reply_text("❌ Valid 10-digit mobile number daal bhai.")

            old_task = self.sniper_tasks.pop(slot_id, None)
            if old_task and not old_task.done():
                old_task.cancel()

            log_step(slot_id, f"Starting human login flow for phone {phone_number}...")
            await update.message.reply_text(f"🔍 Opening product page for {slot_id} (Stealth Mode)...")

            page = await self.browser.open_product_page(slot_id)
            await asyncio.sleep(1.5)
            await self._destroy_location_popup(page, slot_id)

            account.update(phone_number=phone_number, active=True, current_page="🔐 Opening Login Popup", last_error=None)

            mobile_input = await self._open_login_popup(page, slot_id)
            if mobile_input is None:
                log_step(slot_id, "ERROR: Login popup did not open!")
                screenshot_path = self.screenshots_dir / f"{slot_id}_login_error.png"
                await page.screenshot(path=str(screenshot_path), full_page=False)
                await self.telegram.send_photo(photo_path=str(screenshot_path), caption="❌ Login popup nahi khula.")
                if screenshot_path.exists():
                    screenshot_path.unlink()
                raise RuntimeError("Login popup not opened.")

            await mobile_input.click(force=True)
            await asyncio.sleep(0.3)
            await mobile_input.fill("")
            await page.keyboard.type(phone_number, delay=65)
            await asyncio.sleep(0.8)

            send_otp_button = await self._find_send_otp_button(page)
            if send_otp_button is None:
                log_step(slot_id, "ERROR: Continue button not found!")
                error_ss = self.screenshots_dir / f"{slot_id}_continue_btn_err.png"
                await page.screenshot(path=str(error_ss), full_page=False)
                await self.telegram.send_photo(photo_path=str(error_ss), caption="❌ Continue button nahi mila.")
                if error_ss.exists():
                    error_ss.unlink()
                raise RuntimeError("Continue button not found.")

            await send_otp_button.evaluate(
                "(el) => { el.removeAttribute('disabled'); el.removeAttribute('data-disabled'); el.disabled = false; }"
            )
            await send_otp_button.click(force=True, timeout=3000)

            otp_ready = False
            for _ in range(35):
                await asyncio.sleep(0.5)
                if await self._find_otp_inputs(page, phone_number=phone_number):
                    otp_ready = True
                    break

            if not otp_ready:
                log_step(slot_id, "ERROR: OTP boxes did not appear!")
                error_ss = self.screenshots_dir / f"{slot_id}_otp_popup_err.png"
                await page.screenshot(path=str(error_ss), full_page=False)
                await self.telegram.send_photo(photo_path=str(error_ss), caption="❌ OTP box nahi aaya.")
                if error_ss.exists():
                    error_ss.unlink()
                raise RuntimeError("OTP popup did not appear.")

            log_step(slot_id, "SUCCESS: OTP screen is open!")
            account.update(current_page="📩 OTP Sent. Waiting...", last_error=None)
            await update.message.reply_text(f"📩 OTP sent for {slot_id}.\nAb bhej: `/otp {slot_id} 123456`")

        except Exception as exc:
            log_step(slot_id, f"Login failed: {exc}")
            try:
                account.update(last_error=str(exc), active=False)
            except Exception:
                pass
            await update.message.reply_text(f"❌ Login start failed: {exc}")

    async def handle_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        slot_id = "UNKNOWN"
        try:
            args = context.args
            if not args or len(args) < 2:
                return await update.message.reply_text("❌ Format:\n/otp S1-A1 123456")
            slot_id, otp = args[0].upper(), args[1].strip()

            account = self.get_account(slot_id)
            if len(otp) not in [4, 6, 8] or not otp.isdigit():
                return await update.message.reply_text("❌ OTP 4, 6 ya 8 digit ka number hona chahiye.")

            page = await self.browser.get_page(slot_id)

            otp_inputs = []
            for _ in range(20):
                otp_inputs = await self._find_otp_inputs(page, phone_number=account.phone_number or "")
                if otp_inputs:
                    break
                await asyncio.sleep(0.5)

            if not otp_inputs:
                raise RuntimeError("OTP fields page par nahi mile.")

            if len(otp_inputs) == 1:
                await otp_inputs[0].focus()
                await page.keyboard.type(otp, delay=60)
            else:
                boxes = otp_inputs[: len(otp)]
                for i, digit in enumerate(otp):
                    if i < len(boxes):
                        await boxes[i].focus()
                        await page.keyboard.press(digit)
                        await asyncio.sleep(0.06)

            await asyncio.sleep(0.8)

            verify_button = await self._find_verify_button(page)
            if verify_button is None:
                raise RuntimeError("Verify button nahi mila.")

            await verify_button.evaluate(
                "(el) => { el.removeAttribute('disabled'); el.removeAttribute('data-disabled'); el.disabled = false; }"
            )
            await verify_button.click(force=True, timeout=3000)
            await asyncio.sleep(3.5)

            page = await self.browser.ensure_product_page(slot_id)
            await self._destroy_location_popup(page, slot_id)
            await self.browser.save_session(slot_id, account.phone_number)
            account.update(logged_in=True, active=True, current_page="✅ Logged In & Saved", last_error=None)
            log_step(slot_id, "Login successful & session saved!")
            await update.message.reply_text(f"✅ Login successful & Session Saved for {slot_id}!")

            task = self.sniper_tasks.get(slot_id)
            if task is None or task.done():
                self.sniper_tasks[slot_id] = asyncio.create_task(self._sniper_worker(slot_id))
                await update.message.reply_text(f"🔫 Sniper AUTO-STARTED for {slot_id}!")

        except Exception as exc:
            log_step(slot_id, f"OTP failed: {exc}")
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

            page = await self.browser.get_page(slot_id)
            if not page.url or page.url == "about:blank":
                page = await self.browser.open_product_page(slot_id)
                await asyncio.sleep(1.0)

            await self._destroy_location_popup(page, slot_id)

            screenshot_path = self.screenshots_dir / f"{slot_id}.png"
            await page.screenshot(path=str(screenshot_path), full_page=False)
            await self.telegram.send_photo(
                photo_path=str(screenshot_path),
                caption=f"🖥 {slot_id}\nState: {account.current_page}",
            )
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
            fresh_url = (
                f"{settings.product_url}?cb={cb}"
                if "?" not in settings.product_url
                else f"{settings.product_url}&cb={cb}"
            )
            await page.goto(fresh_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(1.2)
            await self._destroy_location_popup(page, slot_id)
            await self.browser.save_session(slot_id, account.phone_number)

            account.update(logged_in=True, active=True, current_page="🔄 Manually Refreshed", last_error=None)
            await update.message.reply_text(f"🔄 Hard Refreshed {slot_id} (Session & Indian Region Active)")

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

            task = self.sniper_tasks.pop(slot_id, None)
            if task and not task.done():
                task.cancel()

            await self.browser.close_slot(slot_id)
            self.browser.sessions.delete_session(slot_id)

            try:
                session_dir = self.browser.sessions.session_path(slot_id)
                meta_file = session_dir / "meta.json"
                if meta_file.exists():
                    meta_file.unlink()
            except Exception:
                pass

            account.update(
                phone_number=None,
                logged_in=False,
                active=False,
                current_page="unknown",
                last_error=None,
                wallet_balance=None,
            )
            log_step(slot_id, "Logged out and RAM freed.")
            await update.message.reply_text(
                f"🚪 Successfully logged out & RAM freed for {slot_id}. Slot is now fresh!"
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ Logout failed: {exc}")

    # =========================================================
    # 🎯 SWARM ATTACK SNIPER BACKGROUND WORKER
    # =========================================================
    async def _sniper_worker(self, slot_id: str):
        account = self.get_account(slot_id)

        try:
            slot_num = int(slot_id.split("-A")[-1])
            await asyncio.sleep((slot_num - 1) * 3)
        except Exception:
            pass

        log_step(slot_id, "Swarm Sniper Worker started!")
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

                account.update(current_page="🔄 [STAGE: Hard Refreshing Page]")
                cache_buster = int(time.time())
                fresh_url = (
                    f"{settings.product_url}?cb={cache_buster}"
                    if "?" not in settings.product_url
                    else f"{settings.product_url}&cb={cache_buster}"
                )

                await page.goto(fresh_url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(1.2)
                await self._destroy_location_popup(page, slot_id)

                content = await page.content()
                if "Application error: a client-side exception" in content:
                    account.update(last_error="Website White Screen - Auto Retrying")
                    await asyncio.sleep(4.0)
                    continue

                account.update(current_page="🎯 [STAGE: Selecting Rs.5000]")
                rs_5000_locator = page.locator("text=Rs.5000 Wallet Code >> visible=true")

                if await rs_5000_locator.count() > 0:
                    try:
                        await rs_5000_locator.first.click(force=True, timeout=3000)
                        await rs_5000_locator.first.evaluate(
                            "(el) => { if(el.parentElement) el.parentElement.click(); }"
                        )
                    except Exception as click_err:
                        account.update(last_error=f"Click Note: {str(click_err)[:40]}")
                else:
                    fallback_loc = page.locator("text=5000 >> visible=true")
                    if await fallback_loc.count() > 0:
                        try:
                            await fallback_loc.last.click(force=True, timeout=3000)
                            await fallback_loc.last.evaluate(
                                "(el) => { if(el.parentElement) el.parentElement.click(); }"
                            )
                        except Exception as click_err:
                            account.update(last_error=f"Fallback Note: {str(click_err)[:40]}")
                    else:
                        account.update(last_error="Rs.5000 option not visible")

                await asyncio.sleep(1.2)
                await self._update_live_balance(page, account)

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
                    await asyncio.sleep(1.2)
                    continue

                log_step(slot_id, "🚨 STOCK DETECTED! Triggering Swarm Buy Flow!")
                account.update(current_page="🚨 [STAGE: INITIATING SWARM BUY FLOW!]")

                if not self.stock_event.is_set():
                    self.stock_event.set()
                    asyncio.create_task(self._clear_stock_event_delayed())

                await self.telegram.send_message(
                    f"🚨 STOCK DETECTED in {slot_id}! Swarm attack initiated across all accounts..."
                )

                for target_qty in [2, 1]:
                    try:
                        if target_qty == 1:
                            account.update(current_page="🔄 [STAGE: Retrying with Qty 1]")
                            retry_url = (
                                f"{settings.product_url}?retry={int(time.time())}"
                                if "?" not in settings.product_url
                                else f"{settings.product_url}&retry={int(time.time())}"
                            )
                            await page.goto(retry_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(1.5)
                            await self._destroy_location_popup(page, slot_id)

                            rs_5000_loc = page.locator("text=Rs.5000 Wallet Code >> visible=true")
                            if await rs_5000_loc.count() > 0:
                                await rs_5000_loc.first.click(force=True)
                                await rs_5000_loc.first.evaluate(
                                    "(el) => { if(el.parentElement) el.parentElement.click(); }"
                                )
                                await asyncio.sleep(1.2)

                            pay_btn_1 = page.locator("button >> text='Pay via wallet' >> visible=true").first

                        if target_qty == 2:
                            account.update(current_page="➕ [STAGE: Changing Quantity to 2]")
                            try:
                                plus_btn = page.locator("button:has-text('+') >> visible=true").first
                                await plus_btn.wait_for(state="visible", timeout=3000)
                                await plus_btn.click(force=True, timeout=2000)
                                await plus_btn.evaluate("(el) => el.click()")
                                await asyncio.sleep(1.2)
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
                                caption=(
                                    f"🛒 SWARM BUY ATTEMPT (Qty {target_qty})!\n\n"
                                    f"Slot: {slot_id}\nBalance Info: {wallet_balance_text}"
                                ),
                            )
                            if screenshot_path.exists():
                                screenshot_path.unlink()
                        except Exception:
                            pass

                        if "insufficient" in wallet_balance_text.lower() or "add money" in wallet_balance_text.lower():
                            account.update(current_page="🛑 [STAGE: Stopped - Insufficient Funds]")
                            await self.telegram.send_message(
                                f"🚨 INSUFFICIENT BALANCE in {slot_id}. Buy stopped."
                            )
                            break

                        account.update(current_page="💳 [STAGE: Clicking First Pay Button]")
                        await pay_btn_1.wait_for(state="visible", timeout=5000)
                        await pay_btn_1.click(force=True, timeout=3000)
                        await pay_btn_1.evaluate("(el) => el.click()")

                        account.update(current_page="📝 [STAGE: Waiting for Delivery Popup]")
                        await page.locator("text=Delivery Details >> visible=true").wait_for(
                            state="visible", timeout=6000
                        )
                        await asyncio.sleep(1.2)

                        account.update(current_page="💳 [STAGE: Clicking Final Pay Button]")
                        pay_btn_2 = page.locator("button >> text='Pay via wallet' >> visible=true").last
                        await pay_btn_2.wait_for(state="visible", timeout=5000)
                        await pay_btn_2.click(force=True, timeout=3000)
                        await pay_btn_2.evaluate("(el) => el.click()")

                        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        account.update(current_page="✅ [STAGE: SUCCESS - Code Bought!]")
                        log_step(slot_id, f"✅ CODE PURCHASED! Qty: {target_qty}")
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
                            await self.telegram.send_photo(
                                photo_path=str(error_ss),
                                caption=f"⚠️ Failed Qty {target_qty} for {slot_id}",
                            )
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
                log_step(slot_id, f"Sniper loop error: {err_msg[:60]}")
                account.update(
                    current_page="🛠️ [STAGE: Auto-Healing Tab...]",
                    last_error=f"Self-Healed: {err_msg[:45]}",
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
