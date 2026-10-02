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
                f"🔐
