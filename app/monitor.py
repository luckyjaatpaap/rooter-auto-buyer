import asyncio
from typing import Dict

from .browser import BrowserManager
from .config import settings
from .controller import AccountController


class AccountMonitor:
    def __init__(
        self,
        browser: BrowserManager,
        controller: AccountController,
    ):
        self.browser = browser
        self.controller = controller

        self.running = False
        self.tasks: Dict[str, asyncio.Task] = {}

    async def check_account(self, slot_id: str):
        account = self.controller.get_account(slot_id)

        if not account.active:
            return

        try:
            page = await self.browser.get_page(slot_id)

            current_url = page.url

            # Agar account kisi unexpected page par hai,
            # screenshot + recovery.
            if (
                current_url
                and "shop.rooter.gg" not in current_url
            ):
                await self.controller.recover(
                    slot_id,
                    f"Unexpected page: {current_url}",
                )
                return

            await page.reload(
                wait_until="domcontentloaded",
                timeout=60000,
            )

            account.update(
                current_page=page.url,
                last_error=None,
            )

        except Exception as exc:
            await self.controller.recover(
                slot_id,
                f"Monitor error: {exc}",
            )

    async def monitor_loop(self, slot_id: str):
        while self.running:
            try:
                await self.check_account(slot_id)

            except asyncio.CancelledError:
                break

            except Exception as exc:
                try:
                    await self.controller.recover(
                        slot_id,
                        f"Monitor loop error: {exc}",
                    )
                except Exception:
                    pass

            await asyncio.sleep(
                settings.monitor_interval_seconds
            )

    async def start_account(self, slot_id: str):
        if slot_id in self.tasks:
            return

        task = asyncio.create_task(
            self.monitor_loop(slot_id)
        )

        self.tasks[slot_id] = task

    async def stop_account(self, slot_id: str):
        task = self.tasks.pop(slot_id, None)

        if task is None:
            return

        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    async def start_all(self):
        self.running = True

        for account in self.controller.all_accounts():
            if account.active:
                await self.start_account(
                    account.slot_id
                )

    async def stop_all(self):
        self.running = False

        for slot_id in list(self.tasks.keys()):
            await self.stop_account(slot_id)
