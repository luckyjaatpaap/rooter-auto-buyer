from pathlib import Path
from typing import Dict, Optional

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
    # CREATE 25 ACCOUNT SLOTS
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

    # =========================================================
    # ACCOUNT ACCESS
    # =========================================================

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
    # TELEGRAM COMMAND REGISTRATION
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
    # /start
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
    # /help
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
    # /status
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
    # /login
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

        try:
            page = await self.browser.open_product_page(
                slot_id
            )

            account.update(
                phone_number=phone_number,
                active=True,
                current_page=page.url,
                last_error=None,
            )

            await self.telegram.send_message(
                f"🔐 Login started\n\n"
                f"Slot: {slot_id}\n"
                f"Number: {phone_number}\n\n"
                f"OTP aane ke baad:\n"
                f"/otp {slot_id} 123456"
            )

        except Exception as exc:

            account.update(
                last_error=str(exc),
                active=False,
            )

            await update.message.reply_text(
                f"❌ Login start failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # /otp
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

        if len(otp) != 6 or not otp.isdigit():
            await update.message.reply_text(
                "❌ OTP must be exactly 6 digits."
            )
            return

        try:
            page = await self.browser.get_page(
                slot_id
            )

            # Make sure the Rooter page is still open.
            await self.browser.handle_location_popup(
                page
            )

            # OTP entry will be connected to the
            # verified Rooter selectors in the next
            # login-flow step.
            #
            # We intentionally do not guess selectors.

            account.update(
                current_page=page.url,
                last_error=None,
            )

            await update.message.reply_text(
                f"📩 OTP received for {slot_id}.\n\n"
                "OTP input flow is ready to be "
                "connected after verifying the "
                "actual Rooter OTP selectors."
            )

        except Exception as exc:

            account.update(
                last_error=str(exc)
            )

            await update.message.reply_text(
                f"❌ OTP handling failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # /screen
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

            # IMPORTANT:
            # Capture only the current desktop
            # viewport. Never full_page.
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
                photo_path=str(
                    screenshot_path
                ),
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
                f"❌ Screenshot failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # /refresh
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
                f"🔄 Refreshed\n"
                f"Slot: {slot_id}\n"
                f"Page: {page.url}"
            )

        except Exception as exc:

            account.update(
                last_error=str(exc)
            )

            await update.message.reply_text(
                f"❌ Refresh failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    # =========================================================
    # /logout
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
                f"🚪 Logged out\n\n"
                f"Slot: {slot_id}\n"
                "Session data cleared.\n"
                "Slot is ready for a new number."
            )

        except Exception as exc:

            account.update(
                last_error=str(exc)
            )

            await update.message.reply_text(
                f"❌ Logout failed\n"
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
                photo_path=str(
                    screenshot_path
                ),
                caption=(
                    f"⚠️ RECOVERY\n"
                    f"Slot: {slot_id}\n\n"
                    f"Error:\n"
                    f"{error_message}"
                ),
            )

        except Exception as screenshot_error:

            try:
                await self.telegram.send_message(
                    f"⚠️ RECOVERY\n"
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
                    f"Recovery failed: "
                    f"{recovery_error}"
                )
            )

            try:
                await self.telegram.send_message(
                    f"❌ Recovery failed\n"
                    f"Slot: {slot_id}\n"
                    f"Error: {recovery_error}"
                )
            except Exception:
                pass
