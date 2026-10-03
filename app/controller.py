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
    #
    # ROOTER DESKTOP HEADER:
    #
    #       [ WALLET ] [ PROFILE ]
    #                    ^^^^^^^
    #                    CLICK THIS
    #
    # The wallet is NEVER selected.
    # =========================================================

    async def _open_login_popup(
        self,
        page,
    ):

        # -----------------------------------------------------
        # Check whether login popup is already open.
        # -----------------------------------------------------

        mobile_input = await self._find_mobile_input(
            page
        )

        if mobile_input is not None:
            return mobile_input

        # -----------------------------------------------------
        # STEP 1:
        # Look specifically for semantic profile/account
        # controls.
        # -----------------------------------------------------

        profile_selectors = [
            '[aria-label*="profile" i]',
            '[aria-label*="account" i]',
            '[aria-label*="avatar" i]',
            '[aria-label*="user" i]',
            '[title*="profile" i]',
            '[title*="account" i]',
            '[title*="avatar" i]',
            '[title*="user" i]',
            'img[alt*="profile" i]',
            'img[alt*="avatar" i]',
            'img[alt*="account" i]',
            'img[alt*="user" i]',
        ]

        for selector in profile_selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for index in range(count):

                    item = locator.nth(index)

                    if not await item.is_visible(
                        timeout=500
                    ):
                        continue

                    # First click the actual element.
                    try:

                        await item.click(
                            timeout=4000
                        )

                    except Exception:

                        # If the visible item is an image,
                        # click its parent.
                        try:

                            parent = item.locator(
                                ".."
                            )

                            await parent.click(
                                timeout=4000
                            )

                        except Exception:
                            continue

                    await page.wait_for_timeout(
                        1000
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

        # -----------------------------------------------------
        # STEP 2:
        # Exact desktop layout logic.
        #
        # Only small controls in the upper-right area
        # are considered.
        #
        # Wallet-like controls are excluded.
        # Profile/account-like controls get priority.
        # If semantic information is unavailable,
        # the RIGHTMOST small icon is tried first.
        # -----------------------------------------------------

        header_controls = page.locator(
            "header button, "
            "header [role='button'], "
            "header a"
        )

        candidates = []

        try:

            count = await header_controls.count()

            viewport_width = await page.evaluate(
                "window.innerWidth"
            )

            for index in range(count):

                try:

                    item = header_controls.nth(index)

                    if not await item.is_visible(
                        timeout=300
                    ):
                        continue

                    box = await item.bounding_box()

                    if not box:
                        continue

                    x = box["x"]
                    y = box["y"]
                    width = box["width"]
                    height = box["height"]

                    # Only header/top controls.
                    if y > 150:
                        continue

                    # Profile/wallet are icon-sized.
                    if width > 110 or height > 110:
                        continue

                    # Must be in the right-side area.
                    if x < viewport_width * 0.65:
                        continue

                    aria = (
                        await item.get_attribute(
                            "aria-label"
                        )
                        or ""
                    )

                    title = (
                        await item.get_attribute(
                            "title"
                        )
                        or ""
                    )

                    class_name = (
                        await item.get_attribute(
                            "class"
                        )
                        or ""
                    )

                    text = ""

                    try:
                        text = (
                            await item.inner_text(
                                timeout=200
                            )
                        )
                    except Exception:
                        pass

                    info = (
                        f"{aria} "
                        f"{title} "
                        f"{class_name} "
                        f"{text}"
                    ).lower()

                    # -------------------------------------------------
                    # IMPORTANT:
                    # Wallet must NEVER be clicked.
                    # -------------------------------------------------

                    wallet_words = [
                        "wallet",
                        "balance",
                        "credit",
                        "credits",
                        "coin",
                        "money",
                    ]

                    if any(
                        word in info
                        for word in wallet_words
                    ):
                        continue

                    # -------------------------------------------------
                    # Score profile candidates.
                    # -------------------------------------------------

                    score = 0

                    profile_words = [
                        "profile",
                        "account",
                        "avatar",
                        "user",
                        "login",
                        "sign in",
                    ]

                    if any(
                        word in info
                        for word in profile_words
                    ):
                        score += 10000

                    # Rightmost gets priority.
                    score += int(x * 10)

                    # Icon-sized control.
                    if (
                        20 <= width <= 90
                        and 20 <= height <= 90
                    ):
                        score += 100

                    candidates.append(
                        (
                            score,
                            x,
                            item,
                        )
                    )

                except Exception:
                    continue

        except Exception:
            pass

        # -----------------------------------------------------
        # Highest score first.
        # -----------------------------------------------------

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        for _, _, item in candidates:

            try:

                await item.scroll_into_view_if_needed()

                await item.click(
                    timeout=5000
                )

                await page.wait_for_timeout(
                    1200
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

        # -----------------------------------------------------
        # STEP 3:
        # Very specific fallback:
        #
        # Find wallet-looking control, then choose the
        # nearest small clickable control immediately
        # to its RIGHT.
        #
        # This directly models:
        #
        #       WALLET -> PROFILE
        # -----------------------------------------------------

        try:

            wallet_locators = page.locator(
                "[aria-label*='wallet' i], "
                "[title*='wallet' i], "
                "[class*='wallet' i]"
            )

            wallet_count = await wallet_locators.count()

            for wallet_index in range(
                wallet_count
            ):

                try:

                    wallet = wallet_locators.nth(
                        wallet_index
                    )

                    if not await wallet.is_visible(
                        timeout=300
                    ):
                        continue

                    wallet_box = (
                        await wallet.bounding_box()
                    )

                    if not wallet_box:
                        continue

                    wallet_right = (
                        wallet_box["x"]
                        + wallet_box["width"]
                    )

                    nearby = []

                    for index in range(
                        await header_controls.count()
                    ):

                        try:

                            item = header_controls.nth(
                                index
                            )

                            if not await item.is_visible(
                                timeout=200
                            ):
                                continue

                            box = (
                                await item.bounding_box()
                            )

                            if not box:
                                continue

                            candidate_left = box["x"]

                            distance = (
                                candidate_left
                                - wallet_right
                            )

                            # Profile is immediately to wallet's
                            # right, not far away.
                            if (
                                0 <= distance <= 180
                                and box["width"] <= 110
                                and box["height"] <= 110
                            ):

                                nearby.append(
                                    (
                                        distance,
                                        item,
                                    )
                                )

                        except Exception:
                            continue

                    # Nearest control to the right of wallet.
                    nearby.sort(
                        key=lambda item: item[0]
                    )

                    for _, item in nearby:

                        try:

                            await item.click(
                                timeout=5000
                            )

                            await page.wait_for_timeout(
                                1200
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

        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[inputmode="numeric"]',
            'input[placeholder*="OTP" i]',
            'input[placeholder*="code" i]',
            'input[aria-label*="OTP" i]',
            'input[aria-label*="code" i]',
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

        # Fallback.
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
            # 1. Open product page
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
            # 2. PROFILE ICON
            # -------------------------------------------------

            mobile_input = (
                await self._open_login_popup(
                    page
                )
            )

            if mobile_input is None:

                # Take diagnostic screenshot.
                screenshot_path = (
                    self.screenshots_dir
                    / f"{slot_id}_login_profile_error.png"
                )

                try:

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
                            "❌ PROFILE ICON DETECTION FAILED\n\n"
                            f"Slot: {slot_id}\n"
                            "Expected: Wallet → Profile\n"
                            f"Page: {page.url}"
                        ),
                    )

                except Exception:
                    pass

                raise RuntimeError(
                    "Rooter Login popup could not be opened "
                    "from the top-right profile icon."
                )

            # -------------------------------------------------
            # 3. Fill mobile number
            # -------------------------------------------------

            await mobile_input.fill(
                phone_number
            )

            # -------------------------------------------------
            # 4. Continue / Send OTP
            # -------------------------------------------------

            send_otp_button = (
                await self._find_send_otp_button(
                    page
                )
            )

            if send_otp_button is None:

                raise RuntimeError(
                    "Rooter Continue button "
                    "was not found."
                )

            await send_otp_button.click(
                timeout=5000
            )

            # -------------------------------------------------
            # 5. Wait for OTP popup
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

            # -------------------------------------------------
            # 1. Get current OTP page
            # -------------------------------------------------

            page = await self.browser.get_page(
                slot_id
            )

            await self.browser.handle_location_popup(
                page
            )

            # -------------------------------------------------
            # 2. Find OTP inputs
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
            # 3. Fill OTP
            #
            # Supports:
            # - single 6-digit input
            # - six separate boxes
            # -------------------------------------------------

            if len(otp_inputs) == 1:

                await otp_inputs[0].fill(
                    otp
                )

            else:

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
            # 4. Verify Now
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
            # 5. Wait for successful login
            # -------------------------------------------------

            await page.wait_for_timeout(
                3000
            )

            await self.browser.handle_location_popup(
                page
            )

            # -------------------------------------------------
            # 6. Return to PlayStation product page
            # -------------------------------------------------

            page = await self.browser.ensure_product_page(
                slot_id
            )

            await page.wait_for_timeout(
                1500
            )

            # -------------------------------------------------
            # 7. Save authenticated session
            # -------------------------------------------------

            await self.browser.save_session(
                slot_id
            )

            # -------------------------------------------------
            # 8. Mark account logged in
            # -------------------------------------------------

            account.update(
                logged_in=True,
                active=True,
                current_page=page.url,
                last_error=None,
            )

            # -------------------------------------------------
            # 9. Login-success screenshot
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
