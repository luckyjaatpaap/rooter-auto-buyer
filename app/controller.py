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
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        path = screenshot_dir / f"{slot_id}.png"

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

        if not page.url or page.url == "about:blank":
            return await self.open_product(slot_id)

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
