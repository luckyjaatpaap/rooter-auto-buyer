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

        for service in range(1, settings.services + 1):
            for account in range(1, settings.accounts_per_service + 1):
                slot_id = f"S{service}-A{account}"

                self.accounts[slot_id] = AccountState(
                    slot_id=slot_id
                )

    # ---------------------------------------------------------
    # ACCOUNT HELPERS
    # ---------------------------------------------------------

    def get_account(self, slot_id: str) -> AccountState:
        account = self.accounts.get(slot_id)

        if account is None:
            raise ValueError(
                f"Unknown slot: {slot_id}"
            )

        return account

    def all_accounts(self):
        return self.accounts.values()

    def _parse_args(self, update: Update):
        if update.message is None:
            return []

        return update.message.text.strip().split()[1:]

    async def _send(
        self,
        update: Update,
        text: str,
    ):
        if update.message:
            await update.message.reply_text(text)

    # ---------------------------------------------------------
    # /start
    # ---------------------------------------------------------

    async def handle_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        await self._send(
            update,
            (
                "🤖 Rooter Auto Buyer\n\n"
                f"Services: {settings.services}\n"
                f"Accounts per service: "
                f"{settings.accounts_per_service}\n"
                f"Total slots: {settings.total_slots}\n\n"
                "Use /status to see account status.\n"
                "Use /help for commands."
            ),
        )

    # ---------------------------------------------------------
    # /status
    # ---------------------------------------------------------

    async def handle_status(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        lines = [
            "📊 Account Status",
            "",
        ]

        for account in self.all_accounts():
            phone = account.phone_number or "-"
            login = "✅" if account.logged_in else "❌"
            active = "🟢" if account.active else "⚪"

            lines.append(
                f"{active} {account.slot_id} | "
                f"Login {login} | {phone}"
            )

        await self._send(
            update,
            "\n".join(lines),
        )

    # ---------------------------------------------------------
    # /login S1-A1 9876543210
    # ---------------------------------------------------------

    async def handle_login(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        args = self._parse_args(update)

        if len(args) < 2:
            await self._send(
                update,
                (
                    "❌ Format:\n"
                    "/login S1-A1 9876543210"
                ),
            )
            return

        slot_id = args[0]
        phone_number = args[1]

        try:
            account = self.get_account(slot_id)

        except ValueError as exc:
            await self._send(
                update,
                f"❌ {exc}",
            )
            return

        try:
            page = await self.browser.open_product_page(
                slot_id
            )

            account.update(
                phone_number=phone_number,
                current_page=page.url,
                active=True,
                last_error=None,
            )

            await self.telegram.send_message(
                (
                    "🔐 Login started\n"
                    f"Slot: {slot_id}\n"
                    f"Number: {phone_number}\n\n"
                    "OTP aane ke baad:\n"
                    f"/otp {slot_id} 123456"
                )
            )

        except Exception as exc:
            await self.recover(
                slot_id,
                f"Login start error: {exc}",
            )

    # ---------------------------------------------------------
    # /otp S1-A1 123456
    # ---------------------------------------------------------

    async def handle_otp(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        args = self._parse_args(update)

        if len(args) < 2:
            await self._send(
                update,
                (
                    "❌ Format:\n"
                    "/otp S1-A1 123456"
                ),
            )
            return

        slot_id = args[0]
        otp = args[1]

        try:
            account = self.get_account(slot_id)

        except ValueError as exc:
            await self._send(
                update,
                f"❌ {exc}",
            )
            return

        if len(otp) != 6 or not otp.isdigit():
            await self._send(
                update,
                "❌ OTP must be exactly 6 digits.",
            )
            return

        try:
            page = await self.browser.get_page(
                slot_id
            )

            account.update(
                current_page=page.url,
                last_error=None,
            )

            # Actual OTP interaction will be added
            # after Rooter's login DOM/selectors
            # are verified.

            await self.browser.save_session(
                slot_id
            )

            screenshot_path = await self.take_screenshot(
                slot_id
            )

            account.update(
                logged_in=True,
                active=True,
                last_screenshot=screenshot_path,
            )

            await self.telegram.send_message(
                (
                    "✅ OTP received\n"
                    f"Slot: {slot_id}\n\n"
                    "Login state has been recorded."
                )
            )

            await self.telegram.send_photo(
                screenshot_path,
                caption=(
                    f"📸 Login state — {slot_id}"
                ),
            )

        except Exception as exc:
            await self.recover(
                slot_id,
                f"OTP error: {exc}",
            )

    # ---------------------------------------------------------
    # /logout S1-A1
    # ---------------------------------------------------------

    async def handle_logout(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        args = self._parse_args(update)

        if len(args) < 1:
            await self._send(
                update,
                "❌ Format:\n/logout S1-A1",
            )
            return

        slot_id = args[0]

        try:
            account = self.get_account(slot_id)

        except ValueError as exc:
            await self._send(
                update,
                f"❌ {exc}",
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

            await self._send(
                update,
                (
                    "🗑️ Slot cleared completely.\n\n"
                    f"Slot: {slot_id}\n"
                    "Session/cookies/storage removed.\n"
                    "This slot is ready for a new number."
                ),
            )

        except Exception as exc:
            await self._send(
                update,
                f"❌ Logout error: {exc}",
            )

    # ---------------------------------------------------------
    # /screen S1-A1
    # ---------------------------------------------------------

    async def handle_screen(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        args = self._parse_args(update)

        if len(args) < 1:
            await self._send(
                update,
                "❌ Format:\n/screen S1-A1",
            )
            return

        slot_id = args[0]

        try:
            self.get_account(slot_id)

        except ValueError as exc:
            await self._send(
                update,
                f"❌ {exc}",
            )
            return

        try:
            screenshot_path = await self.take_screenshot(
                slot_id
            )

            await self.telegram.send_photo(
                screenshot_path,
                caption=(
                    f"📸 Current screen — {slot_id}"
                ),
            )

        except Exception as exc:
            await self._send(
                update,
                f"❌ Screenshot error: {exc}",
            )

    # ---------------------------------------------------------
    # /refresh S1-A1
    # ---------------------------------------------------------

    async def handle_refresh(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        args = self._parse_args(update)

        if len(args) < 1:
            await self._send(
                update,
                "❌ Format:\n/refresh S1-A1",
            )
            return

        slot_id = args[0]

        try:
            account = self.get_account(slot_id)

            page = await self.browser.open_product_page(
                slot_id
            )

            account.update(
                current_page=page.url,
                last_error=None,
            )

            await self._send(
                update,
                (
                    "🔄 Page refreshed\n"
                    f"Slot: {slot_id}\n"
                    f"URL: {page.url}"
                ),
            )

        except Exception as exc:
            await self.recover(
                slot_id,
                f"Refresh error: {exc}",
            )

    # ---------------------------------------------------------
    # /help
    # ---------------------------------------------------------

    async def handle_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        await self._send(
            update,
            (
                "🤖 Rooter Auto Buyer Commands\n\n"
                "/start\n"
                "/status\n"
                "/login S1-A1 9876543210\n"
                "/otp S1-A1 123456\n"
                "/screen S1-A1\n"
                "/refresh S1-A1\n"
                "/logout S1-A1\n"
                "/help"
            ),
        )

    # ---------------------------------------------------------
    # SCREENSHOT
    # ---------------------------------------------------------

    async def take_screenshot(
        self,
        slot_id: str,
    ) -> str:
        account = self.get_account(slot_id)

        page = await self.browser.get_page(
            slot_id
        )

        if not page.url or page.url == "about:blank":
            page = await self.browser.open_product_page(
                slot_id
            )

        screenshot_dir = Path(
            settings.screenshots_dir
        )

        screenshot_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        screenshot_path = (
            screenshot_dir
            / f"{slot_id}.png"
        )

        await page.screenshot(
            path=str(screenshot_path),
            full_page=True,
        )

        account.update(
            current_page=page.url,
            last_screenshot=str(
                screenshot_path
            ),
        )

        return str(screenshot_path)

    # ---------------------------------------------------------
    # RECOVERY
    # ---------------------------------------------------------

    async def recover(
        self,
        slot_id: str,
        error: str,
    ):
        try:
            account = self.get_account(
                slot_id
            )

            account.update(
                last_error=error,
            )

            screenshot_path = None

            try:
                screenshot_path = await self.take_screenshot(
                    slot_id
                )

            except Exception:
                pass

            await self.telegram.send_message(
                (
                    "🚨 Account error\n"
                    f"Slot: {slot_id}\n\n"
                    f"{error}\n\n"
                    "Recovery started..."
                )
            )

            if screenshot_path:
                try:
                    await self.telegram.send_photo(
                        screenshot_path,
                        caption=(
                            f"🚨 Error screenshot — "
                            f"{slot_id}"
                        ),
                    )

                except Exception:
                    pass

            page = await self.browser.open_product_page(
                slot_id
            )

            account.update(
                current_page=page.url,
                last_error=None,
            )

            await self.telegram.send_message(
                (
                    "♻️ Recovery successful\n"
                    f"Slot: {slot_id}\n"
                    "Returned to PlayStation page."
                )
            )

        except Exception as recovery_error:
            try:
                await self.telegram.send_message(
                    (
                        "❌ Recovery failed\n"
                        f"Slot: {slot_id}\n\n"
                        f"{recovery_error}"
                    )
                )

            except Exception:
                pass

    # ---------------------------------------------------------
    # TELEGRAM COMMAND CONNECTION
    # ---------------------------------------------------------

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
