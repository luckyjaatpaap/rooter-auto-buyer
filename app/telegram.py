from pathlib import Path
from typing import Callable, Awaitable, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from .config import settings


CommandCallback = Callable[
    [Update, ContextTypes.DEFAULT_TYPE],
    Awaitable[None],
]


class TelegramBot:
    def __init__(self):
        self.application: Optional[Application] = None

        self.callbacks: dict[str, CommandCallback] = {}

    def register_command(
        self,
        command: str,
        callback: CommandCallback,
    ):
        self.callbacks[command] = callback

    def _create_handler(self, command: str):
        async def handler(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
        ):
            callback = self.callbacks.get(command)

            if callback is None:
                return

            await callback(update, context)

        return handler

    def build(self):
        if not settings.telegram_bot_token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is not configured"
            )

        self.application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )

        commands = [
            "start",
            "status",
            "login",
            "otp",
            "logout",
            "screen",
            "refresh",
            "help",
        ]

        for command in commands:
            self.application.add_handler(
                CommandHandler(
                    command,
                    self._create_handler(command),
                )
            )

        return self.application

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
    ):
        if self.application is None:
            raise RuntimeError(
                "Telegram application is not built"
            )

        target_chat = chat_id or settings.telegram_chat_id

        if not target_chat:
            raise RuntimeError(
                "TELEGRAM_CHAT_ID is not configured"
            )

        bot = self.application.bot

        await bot.send_message(
            chat_id=target_chat,
            text=text,
        )

    async def send_photo(
        self,
        photo_path: str,
        caption: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        if self.application is None:
            raise RuntimeError(
                "Telegram application is not built"
            )

        target_chat = chat_id or settings.telegram_chat_id

        if not target_chat:
            raise RuntimeError(
                "TELEGRAM_CHAT_ID is not configured"
            )

        path = Path(photo_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Screenshot not found: {photo_path}"
            )

        bot = self.application.bot

        with path.open("rb") as photo:
            await bot.send_photo(
                chat_id=target_chat,
                photo=photo,
                caption=caption,
            )

    async def start(self):
        if self.application is None:
            self.build()

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

    async def stop(self):
        if self.application is None:
            return

        if self.application.updater.running:
            await self.application.updater.stop()

        await self.application.stop()
        await self.application.shutdown()
