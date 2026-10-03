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

        self.screenshots_dir = Path(
            settings.screenshots_dir
        )

        self.screenshots_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._create_slots()

    # =========================================================
    # SLOT MANAGEMENT
    # =========================================================

    def _create_slots(self):

        for service_number in range(
            1,
            settings.services + 1,
        ):

            for account_number in range(
                1,
                settings.accounts_per_service + 1,
            ):

                slot_id = (
                    f"S{service_number}-A{account_number}"
                )

                self.accounts[slot_id] = AccountState(
                    slot_id=slot_id
                )

    def get_account(
        self,
        slot_id: str,
    ) -> AccountState:

        account = self.accounts.get(
            slot_id
        )

        if account is None:
            raise ValueError(
                f"Unknown slot: {slot_id}"
            )

        return account

    def all_accounts(self):

        return list(
            self.accounts.values()
        )

    # =========================================================
    # COMMAND CONNECTION
    # =========================================================

    def connect_commands(self):

        self.telegram.register_command(
            "start",
            self.handle_start,
        )

        self.telegram.register_command(
            "status",
            self.handle_status,
        )

        self.telegram.register_command(
            "login",
            self.handle_login,
        )

        self.telegram.register_command(
            "otp",
            self.handle_otp,
        )

        self.telegram.register_command(
            "logout",
            self.handle_logout,
        )

        self.telegram.register_command(
            "screen",
            self.handle_screen,
        )

        self.telegram.register_command(
            "refresh",
            self.handle_refresh,
        )

        self.telegram.register_command(
            "help",
            self.handle_help,
        )

    # =========================================================
    # START
    # =========================================================

    async def handle_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        await update.message.reply_text(
            "🤖 Rooter Auto Buyer\n\n"
            "System online.\n"
            f"Total slots: {settings.total_slots}\n"
            f"Services: {settings.services}\n"
            f"Accounts/service: "
            f"{settings.accounts_per_service}\n\n"
            "Use /status to check slots."
        )

    # =========================================================
    # HELP
    # =========================================================

    async def handle_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        await update.message.reply_text(
            "📖 Commands\n\n"
            "/start\n"
            "/status\n"
            "/login S1-A1 9876543210\n"
            "/otp S1-A1 123456\n"
            "/screen S1-A1\n"
            "/refresh S1-A1\n"
            "/logout S1-A1\n"
            "/help"
        )

    # =========================================================
    # STATUS
    # =========================================================

    async def handle_status(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        lines = [
            "📊 ACCOUNT STATUS",
            "",
        ]

        for account in self.all_accounts():

            phone = (
                account.phone_number
                if account.phone_number
                else "-"
            )

            login_state = (
                "LOGGED IN"
                if account.logged_in
                else "NOT LOGGED IN"
            )

            active_state = (
                "ACTIVE"
                if account.active
                else "INACTIVE"
            )

            balance = (
                f"₹{account.wallet_balance:.2f}"
                if account.wallet_balance is not None
                else "-"
            )

            lines.append(
                f"{account.slot_id} | "
                f"{login_state} | "
                f"{active_state} | "
                f"Balance: {balance}"
            )

            if phone != "-":
                lines.append(
                    f"  📱 {phone}"
                )

            lines.append(
                f"  📍 {account.current_page}"
            )

            if account.last_error:
                lines.append(
                    f"  ⚠️ {account.last_error}"
                )

        await update.message.reply_text(
            "\n".join(lines)
        )

    # =========================================================
    # FIND MOBILE INPUT
    # =========================================================

    async def _find_mobile_input(
        self,
        page,
    ):

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

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for index in range(count):

                    item = locator.nth(index)

                    if await item.is_visible(
                        timeout=500
                    ):
                        return item

            except Exception:
                continue

        return None

    # =========================================================
    # OPEN LOGIN POPUP
    # =========================================================

    async def _open_login_popup(self, page: Page) -> bool:
    """
    Rooter login flow:
    Top-right has exactly two important icon buttons:
      LEFT  = Wallet
      RIGHT = Profile

    Always target the right-side profile control.
    """

    async def login_popup_open() -> bool:
        selectors = [
            'input[type="tel"]',
            'input[inputmode="tel"]',
            'input[autocomplete="tel"]',
            'input[name*="mobile" i]',
            'input[name*="phone" i]',
        ]

        for selector in selectors:
            locator = page.locator(selector)

            for i in range(await locator.count()):
                try:
                    if await locator.nth(i).is_visible(
                        timeout=300
                    ):
                        return True
                except Exception:
                    pass

        return False

    # Already open?
    if await login_popup_open():
        return True

    # ---------------------------------------------------------
    # Find top-right controls only
    # ---------------------------------------------------------

    controls = page.locator(
        "header button, "
        "header [role='button'], "
        "header a"
    )

    candidates = []

    for i in range(await controls.count()):

        try:
            element = controls.nth(i)

            if not await element.is_visible(timeout=300):
                continue

            box = await element.bounding_box()

            if not box:
                continue

            x = box["x"]
            y = box["y"]
            width = box["width"]
            height = box["height"]

            # Only small icon-like controls near top-right.
            if y > 150:
                continue

            if width > 100 or height > 100:
                continue

            # Must actually be near the right side.
            viewport_width = await page.evaluate(
                "window.innerWidth"
            )

            if x < viewport_width * 0.65:
                continue

            aria = (
                await element.get_attribute("aria-label")
                or ""
            ).lower()

            title = (
                await element.get_attribute("title")
                or ""
            ).lower()

            cls = (
                await element.get_attribute("class")
                or ""
            ).lower()

            text = ""

            try:
                text = (
                    await element.inner_text(
                        timeout=200
                    )
                ).strip().lower()
            except Exception:
                pass

            info = f"{aria} {title} {cls} {text}"

            # Never choose wallet.
            if any(word in info for word in [
                "wallet",
                "balance",
                "credit",
                "coin",
            ]):
                continue

            # Profile/account is a direct match.
            profile_score = 0

            if any(word in info for word in [
                "profile",
                "account",
                "avatar",
                "user",
            ]):
                profile_score += 100

            # Rightmost controls get priority.
            profile_score += int(x)

            candidates.append(
                (
                    profile_score,
                    x,
                    element,
                )
            )

        except Exception:
            continue

    # Rightmost/profile candidate first.
    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    for _, _, element in candidates:

        try:
            await element.scroll_into_view_if_needed()

            await element.click(
                timeout=5000
            )

            await page.wait_for_timeout(1200)

            if await login_popup_open():
                return True

        except Exception:
            continue

    return False

        # -----------------------------------------------------
        # Desktop header fallback
        #
        # Profile is the right-side account control,
        # immediately after the wallet control.
        # We try header buttons from right to left.
        # -----------------------------------------------------

        header_controls = page.locator(
            "header button, "
            "header [role='button'], "
            "header a"
        )

        try:

            count = await header_controls.count()

            for index in range(
                count - 1,
                -1,
                -1,
            ):

                try:

                    item = header_controls.nth(index)

                    if not await item.is_visible(
                        timeout=300
                    ):
                        continue

                    await item.click(
                        timeout=3000
                    )

                    await page.wait_for_timeout(
                        800
                    )

                    mobile_input = (
                        await self._find_mobile_input(
                            page
                        )
                    )

                    if mobile_input is not None:
                        return mobile_input

                except Exception:
                    continue

        except Exception:
            pass

        return None

    # =========================================================
    # SEND OTP / CONTINUE BUTTON
    # =========================================================

    async def _find_send_otp_button(
        self,
        page,
    ):

        candidates = [
            page.get_by_role(
                "button",
                name="Send OTP",
                exact=True,
            ),
            page.get_by_text(
                "Send OTP",
                exact=True,
            ),
            page.locator(
                'button:has-text("Send OTP")'
            ),
            page.get_by_role(
                "button",
                name="Continue",
                exact=True,
            ),
            page.get_by_text(
                "Continue",
                exact=True,
            ),
            page.locator(
                'button:has-text("Continue")'
            ),
        ]

        for locator in candidates:

            try:

                count = await locator.count()

                for index in range(count):

                    item = locator.nth(index)

                    if await item.is_visible(
                        timeout=500
                    ):

                        return item

            except Exception:
                continue

        return None

    # =========================================================
    # OTP INPUTS
    # =========================================================

    async def _find_otp_inputs(
        self,
        page,
    ):

        # First try common OTP selectors.
        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[inputmode="numeric"]',
            'input[placeholder*="OTP" i]',
            'input[placeholder*="code" i]',
        ]

        found = []

        for selector in selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for index in range(count):

                    item = locator.nth(index)

                    if await item.is_visible(
                        timeout=300
                    ):

                        found.append(item)

                if found:
                    return found

            except Exception:
                continue

        # Fallback: visible numeric/tel inputs.
        selectors = [
            'input[type="tel"]',
            'input[type="number"]',
        ]

        for selector in selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for index in range(count):

                    item = locator.nth(index)

                    if await item.is_visible(
                        timeout=300
                    ):

                        found.append(item)

                if found:
                    return found

            except Exception:
                continue

        return found

    # =========================================================
    # VERIFY BUTTON
    # =========================================================

    async def _find_verify_button(
        self,
        page,
    ):

        candidates = [
            page.get_by_role(
                "button",
                name="Verify Now",
                exact=True,
            ),
            page.get_by_text(
                "Verify Now",
                exact=True,
            ),
            page.locator(
                'button:has-text("Verify Now")'
            ),
        ]

        for locator in candidates:

            try:

                count = await locator.count()

                for index in range(count):

                    item = locator.nth(index)

                    if await item.is_visible(
                        timeout=500
                    ):

                        return item

            except Exception:
                continue

        return None

    # =========================================================
    # LOGIN
    # =========================================================

    async def handle_login(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        args = context.args

        if len(args) < 2:

            await update.message.reply_text(
                "❌ Format:\n"
                "/login S1-A1 9876543210"
            )

            return

        slot_id = args[0].upper()
        phone_number = args[1].strip()

        try:

            account = self.get_account(
                slot_id
            )

        except ValueError as exc:

            await update.message.reply_text(
                f"❌ {exc}"
            )

            return

        if account.logged_in:

            await update.message.reply_text(
                f"⚠️ {slot_id} is already logged in."
            )

            return

        if (
            not phone_number.isdigit()
            or len(phone_number) != 10
        ):

            await update.message.reply_text(
                "❌ Enter a valid 10-digit "
                "Indian mobile number."
            )

            return

        try:

            # -------------------------------------------------
            # Open target page
            # -------------------------------------------------

            page = await self.browser.open_product_page(
                slot_id
            )

            account.update(
                phone_number=phone_number,
                active=True,
                current_page=page.url,
                last_error=None,
            )

            # -------------------------------------------------
            # PROFILE ICON -> LOGIN POPUP
            # -------------------------------------------------

            mobile_input = (
                await self._open_login_popup(
                    page
                )
            )

            if mobile_input is None:

                raise RuntimeError(
                    "Rooter Login popup could not be opened "
                    "from the top-right profile icon."
                )

            # -------------------------------------------------
            # FILL MOBILE NUMBER
            # -------------------------------------------------

            await mobile_input.fill(
                phone_number
            )

            # -------------------------------------------------
            # SEND OTP
            # -------------------------------------------------

            send_otp_button = (
                await self._find_send_otp_button(
                    page
                )
            )

            if send_otp_button is None:

                raise RuntimeError(
                    "Rooter Send OTP button "
                    "was not found."
                )

            await send_otp_button.click(
                timeout=5000
            )

            # -------------------------------------------------
            # WAIT FOR OTP POPUP
            # -------------------------------------------------

            otp_inputs = []

            for _ in range(20):

                await page.wait_for_timeout(
                    500
                )

                otp_inputs = (
                    await self._find_otp_inputs(
                        page
                    )
                )

                if otp_inputs:
                    break

            if not otp_inputs:

                raise RuntimeError(
                    "OTP verification popup "
                    "did not appear."
                )

            account.update(
                current_page=page.url,
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

            account.update(
                last_error=str(exc),
                active=False,
            )

            await update.message.reply_text(
                "❌ Login start failed\n\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # OTP
    # =========================================================

    async def handle_otp(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        args = context.args

        if len(args) < 2:

            await update.message.reply_text(
                "❌ Format:\n"
                "/otp S1-A1 123456"
            )

            return

        slot_id = args[0].upper()
        otp = args[1].strip()

        try:

            account = self.get_account(
                slot_id
            )

        except ValueError as exc:

            await update.message.reply_text(
                f"❌ {exc}"
            )

            return

        if (
            len(otp) != 6
            or not otp.isdigit()
        ):

            await update.message.reply_text(
                "❌ OTP must be exactly 6 digits."
            )

            return

        try:

            page = await self.browser.get_page(
                slot_id
            )

            await self.browser.handle_location_popup(
                page
            )

            # -------------------------------------------------
            # FIND OTP INPUT(S)
            # -------------------------------------------------

            otp_inputs = []

            for _ in range(10):

                otp_inputs = (
                    await self._find_otp_inputs(
                        page
                    )
                )

                if otp_inputs:
                    break

                await page.wait_for_timeout(
                    500
                )

            if not otp_inputs:

                raise RuntimeError(
                    "OTP input field was not found."
                )

            # -------------------------------------------------
            # FILL OTP
            #
            # Supports:
            # 1. One six-digit input
            # 2. Six separate OTP boxes
            # -------------------------------------------------

            if len(otp_inputs) == 1:

                await otp_inputs[0].fill(
                    otp
                )

            else:

                # Use first six visible boxes.
                boxes = otp_inputs[:6]

                if len(boxes) < 6:

                    raise RuntimeError(
                        "OTP fields were found, "
                        "but six OTP boxes are not available."
                    )

                for index, digit in enumerate(
                    otp
                ):

                    await boxes[index].fill(
                        digit
                    )

            await page.wait_for_timeout(
                500
            )

            # -------------------------------------------------
            # VERIFY NOW
            # -------------------------------------------------

            verify_button = (
                await self._find_verify_button(
                    page
                )
            )

            if verify_button is None:

                raise RuntimeError(
                    "Verify Now button "
                    "was not found."
                )

            await verify_button.click(
                timeout=5000
            )

            # -------------------------------------------------
            # WAIT FOR LOGIN RESULT
            # -------------------------------------------------

            await page.wait_for_timeout(
                3000
            )

            await self.browser.handle_location_popup(
                page
            )

            # -------------------------------------------------
            # RETURN TO PRODUCT PAGE
            # -------------------------------------------------

            page = await self.browser.ensure_product_page(
                slot_id
            )

            await page.wait_for_timeout(
                1500
            )

            # -------------------------------------------------
            # SAVE AUTHENTICATED SESSION
            # -------------------------------------------------

            await self.browser.save_session(
                slot_id
            )

            account.update(
                logged_in=True,
                active=True,
                current_page=page.url,
                last_error=None,
            )

            # -------------------------------------------------
            # LOGIN SUCCESS SCREENSHOT
            # -------------------------------------------------

            screenshot_path = (
                self.screenshots_dir
                / f"{slot_id}_login_success.png"
            )

            await page.screenshot(
                path=str(screenshot_path),
                full_page=False,
            )

            account.update(
                last_screenshot=str(
                    screenshot_path
                )
            )

            await self.telegram.send_photo(
                photo_path=str(
                    screenshot_path
                ),
                caption=(
                    "✅ LOGIN SUCCESSFUL\n\n"
                    f"Slot: {slot_id}\n"
                    f"Number: +91 "
                    f"{account.phone_number}\n"
                    "Session saved."
                ),
            )

            await update.message.reply_text(
                "✅ Login successful\n\n"
                f"Slot: {slot_id}\n"
                f"Number: +91 "
                f"{account.phone_number}\n"
                "Session saved."
            )

        except Exception as exc:

            account.update(
                last_error=str(exc)
            )

            await update.message.reply_text(
                "❌ OTP/Login failed\n\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # SCREENSHOT
    # =========================================================

    async def handle_screen(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        args = context.args

        if len(args) < 1:

            await update.message.reply_text(
                "❌ Format:\n"
                "/screen S1-A1"
            )

            return

        slot_id = args[0].upper()

        try:

            account = self.get_account(
                slot_id
            )

        except ValueError as exc:

            await update.message.reply_text(
                f"❌ {exc}"
            )

            return

        try:

            page = await self.browser.ensure_product_page(
                slot_id
            )

            await page.evaluate(
                "window.scrollTo(0, 0)"
            )

            screenshot_path = (
                self.screenshots_dir
                / f"{slot_id}.png"
            )

            await page.screenshot(
                path=str(screenshot_path),
                full_page=False,
            )

            account.update(
                current_page=page.url,
                last_screenshot=str(
                    screenshot_path
                ),
                last_error=None,
            )

            await self.telegram.send_photo(
                photo_path=str(screenshot_path),
                caption=(
                    f"🖥️ {slot_id}\n"
                    f"Page: {page.url}"
                ),
            )

        except Exception as exc:

            account.update(
                last_error=str(exc)
            )

            await update.message.reply_text(
                "❌ Screenshot failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # REFRESH
    # =========================================================

    async def handle_refresh(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        args = context.args

        if len(args) < 1:

            await update.message.reply_text(
                "❌ Format:\n"
                "/refresh S1-A1"
            )

            return

        slot_id = args[0].upper()

        try:

            account = self.get_account(
                slot_id
            )

        except ValueError as exc:

            await update.message.reply_text(
                f"❌ {exc}"
            )

            return

        try:

            page = await self.browser.get_page(
                slot_id
            )

            await page.reload(
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await self.browser.handle_location_popup(
                page
            )

            await page.wait_for_timeout(
                1500
            )

            await page.evaluate(
                "window.scrollTo(0, 0)"
            )

            account.update(
                current_page=page.url,
                last_error=None,
            )

            await update.message.reply_text(
                "🔄 Refreshed\n"
                f"Slot: {slot_id}\n"
                f"Page: {page.url}"
            )

        except Exception as exc:

            account.update(
                last_error=str(exc)
            )

            await update.message.reply_text(
                "❌ Refresh failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # LOGOUT
    # =========================================================

    async def handle_logout(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        args = context.args

        if len(args) < 1:

            await update.message.reply_text(
                "❌ Format:\n"
                "/logout S1-A1"
            )

            return

        slot_id = args[0].upper()

        try:

            account = self.get_account(
                slot_id
            )

        except ValueError as exc:

            await update.message.reply_text(
                f"❌ {exc}"
            )

            return

        try:

            await self.browser.logout_slot(
                slot_id
            )

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

            account.update(
                last_error=str(exc)
            )

            await update.message.reply_text(
                "❌ Logout failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # RECOVERY
    # =========================================================

    async def recover(
        self,
        slot_id: str,
        error_message: str,
    ):

        try:

            account = self.get_account(
                slot_id
            )

            account.update(
                last_error=error_message
            )

        except Exception:
            return

        screenshot_path = (
            self.screenshots_dir
            / f"{slot_id}_error.png"
        )

        try:

            page = await self.browser.get_page(
                slot_id
            )

            await page.screenshot(
                path=str(screenshot_path),
                full_page=False,
            )

            account.update(
                last_screenshot=str(
                    screenshot_path
                )
            )

            await self.telegram.send_photo(
                photo_path=str(screenshot_path),
                caption=(
                    "⚠️ RECOVERY\n"
                    f"Slot: {slot_id}\n\n"
                    f"Error:\n"
                    f"{error_message}"
                ),
            )

        except Exception as screenshot_error:

            try:

                await self.telegram.send_message(
                    "⚠️ RECOVERY\n"
                    f"Slot: {slot_id}\n\n"
                    f"Error:\n"
                    f"{error_message}\n\n"
                    f"Screenshot error:\n"
                    f"{screenshot_error}"
                )

            except Exception:
                pass

        try:

            page = await self.browser.open_product_page(
                slot_id
            )

            account.update(
                current_page=page.url,
                last_error=None,
            )

        except Exception as recovery_error:

            account.update(
                last_error=(
                    "Recovery failed: "
                    f"{recovery_error}"
                )
            )

            try:

                await self.telegram.send_message(
                    "❌ Recovery failed\n"
                    f"Slot: {slot_id}\n"
                    f"Error: {recovery_error}"
                )

            except Exception:
                pass
