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

        self.accounts: Dict[str, AccountState] = {
            self._slot_id(service, account): AccountState(
                slot_id=self._slot_id(service, account)
            )
            for service in range(1, settings.services + 1)
            for account in range(1, settings.accounts_per_service + 1)
        }

        self.pending_logins: Dict[str, str] = {}

    @staticmethod
    def _slot_id(service: int, account: int) -> str:
        return f"S{service}-A{account}"

    def get_account(self, slot_id: str) -> AccountState:
        if slot_id not in self.accounts:
            raise ValueError(f"Unknown slot: {slot_id}")

        return self.accounts[slot_id]

    def all_accounts(self):
        return list(self.accounts.values())

    async def screenshot(self, slot_id: str) -> str:
        account = self.get_account(slot_id)

        page = await self.browser.get_page(slot_id)

if not page.url or page.url == "about:blank":
    await page.goto(
        settings.product_url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

screenshot_dir = Path(settings.screenshots_dir)

        await page.screenshot(
            path=str(path),
            full_page=True,
        )

        account.update(
            last_screenshot=str(path),
            current_page=page.url,
            last_error=None,
        )

        return str(path)

    async def open_product(self, slot_id: str):
        account = self.get_account(slot_id)

        page = await self.browser.get_page(slot_id)

        await page.goto(
            settings.product_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        account.update(
            active=True,
            current_page=page.url,
            last_error=None,
        )

        return page

    async def refresh(self, slot_id: str):
        account = self.get_account(slot_id)

        page = await self.browser.get_page(slot_id)

        await page.reload(
            wait_until="domcontentloaded",
            timeout=60000,
        )

        account.update(
            active=True,
            current_page=page.url,
            last_error=None,
        )

        return page

    async def begin_login(
        self,
        slot_id: str,
        phone_number: str,
    ):
        account = self.get_account(slot_id)

        page = await self.browser.get_page(slot_id)

        await page.goto(
            settings.product_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        account.update(
            phone_number=phone_number,
            active=True,
            current_page=page.url,
            last_error=None,
        )

        self.pending_logins[slot_id] = phone_number

        await self.telegram.send_message(
            f"🔐 Login started\n"
            f"Slot: {slot_id}\n"
            f"Number: {phone_number}\n\n"
            f"OTP aane ke baad:\n"
            f"/otp {slot_id} 123456"
        )

    async def submit_otp(
        self,
        slot_id: str,
        otp: str,
    ):
        account = self.get_account(slot_id)

        if slot_id not in self.pending_logins:
            raise RuntimeError(
                f"No pending login for {slot_id}"
            )

        if not otp.isdigit() or len(otp) != 6:
            raise ValueError(
                "OTP must be exactly 6 digits"
            )

        # Actual Rooter OTP field interaction
        # will be added after selector verification.
        #
        # We deliberately do not guess selectors here.

        account.update(
            last_error=None,
            current_page="otp_pending_verification",
        )

        await self.telegram.send_message(
            f"🔑 OTP received for {slot_id}.\n"
            f"OTP verification handler is ready for selector integration."
        )

    async def logout(self, slot_id: str):
        account = self.get_account(slot_id)

        await self.browser.logout_slot(slot_id)

        account.update(
            phone_number=None,
            logged_in=False,
            active=False,
            current_page="logged_out",
            wallet_balance=None,
            last_order_id=None,
            last_screenshot=None,
            last_error=None,
        )

        self.pending_logins.pop(slot_id, None)

        await self.telegram.send_message(
            f"🚪 Logged out\n"
            f"Slot: {slot_id}\n"
            f"Session data cleared."
        )

    async def recover(self, slot_id: str, reason: str):
        account = self.get_account(slot_id)

        account.update(
            last_error=reason,
            current_page="recovering",
        )

        try:
            screenshot = await self.screenshot(slot_id)

            await self.telegram.send_photo(
                screenshot,
                caption=(
                    f"⚠️ Recovery triggered\n"
                    f"Slot: {slot_id}\n"
                    f"Reason: {reason}"
                ),
            )
        except Exception:
            pass

        try:
            await self.open_product(slot_id)

            account.update(
                current_page=settings.product_url,
                last_error=None,
            )

            await self.telegram.send_message(
                f"✅ Recovery complete\n"
                f"Slot: {slot_id}\n"
                f"Returned to PlayStation product page."
            )

        except Exception as exc:
            account.update(
                last_error=str(exc),
                current_page="recovery_failed",
            )

            await self.telegram.send_message(
                f"❌ Recovery failed\n"
                f"Slot: {slot_id}\n"
                f"Error: {exc}"
            )

    async def handle_status(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        lines = ["📊 Account Status", ""]

        for account in self.accounts.values():
            status = "🟢" if account.active else "⚪"

            login = (
                "Logged in"
                if account.logged_in
                else "Not logged in"
            )

            lines.append(
                f"{status} {account.slot_id} | {login} | "
                f"{account.current_page}"
            )

        await update.message.reply_text(
            "\n".join(lines)
        )

    async def handle_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        await update.message.reply_text(
            "🤖 Rooter Account Manager\n\n"
            "Commands:\n"
            "/status\n"
            "/login S1-A1 9876543210\n"
            "/otp S1-A1 123456\n"
            "/screen S1-A1\n"
            "/refresh S1-A1\n"
            "/logout S1-A1\n"
            "/help"
        )

    async def handle_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        await update.message.reply_text(
            "📖 Commands\n\n"
            "/status — all account status\n"
            "/login SLOT NUMBER — start login\n"
            "/otp SLOT OTP — verify OTP\n"
            "/screen SLOT — screenshot\n"
            "/refresh SLOT — refresh page\n"
            "/logout SLOT — clear account session\n"
        )

    async def handle_login(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        if len(context.args) != 2:
            await update.message.reply_text(
                "Use: /login S1-A1 9876543210"
            )
            return

        slot_id, phone = context.args

        try:
            self.get_account(slot_id)
            await self.begin_login(slot_id, phone)

        except Exception as exc:
            await update.message.reply_text(
                f"❌ {exc}"
            )

    async def handle_otp(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        if len(context.args) != 2:
            await update.message.reply_text(
                "Use: /otp S1-A1 123456"
            )
            return

        slot_id, otp = context.args

        try:
            await self.submit_otp(slot_id, otp)

        except Exception as exc:
            await update.message.reply_text(
                f"❌ {exc}"
            )

    async def handle_logout(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        if len(context.args) != 1:
            await update.message.reply_text(
                "Use: /logout S1-A1"
            )
            return

        try:
            await self.logout(context.args[0])

        except Exception as exc:
            await update.message.reply_text(
                f"❌ {exc}"
            )

    async def handle_screen(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        if len(context.args) != 1:
            await update.message.reply_text(
                "Use: /screen S1-A1"
            )
            return

        slot_id = context.args[0]

        try:
            path = await self.screenshot(slot_id)

            await self.telegram.send_photo(
                path,
                caption=f"📸 {slot_id} current screen",
            )

        except Exception as exc:
            await update.message.reply_text(
                f"❌ {exc}"
            )

    async def handle_refresh(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        if len(context.args) != 1:
            await update.message.reply_text(
                "Use: /refresh S1-A1"
            )
            return

        slot_id = context.args[0]

        try:
            await self.refresh(slot_id)

            await update.message.reply_text(
                f"🔄 Refreshed: {slot_id}"
            )

        except Exception as exc:
            await update.message.reply_text(
                f"❌ {exc}"
            )

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
