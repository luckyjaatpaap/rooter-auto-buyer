from pathlib import Path
from typing import Awaitable, Callable, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
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
        # Agar application pehle se build ho chuki hai toh dynamically add kar do
        if self.application is not None:
            self.application.add_handler(
                CommandHandler(
                    command,
                    self._create_handler(command),
                    block=False,
                )
            )

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

    async def _document_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Agar user .json cookie file caption '/cookie S1-A1' ke sath bheje toh handle karega."""
        if not update.message or not update.message.caption:
            return
        caption = update.message.caption.strip()
        if caption.lower().startswith("/cookie"):
            parts = caption.split()
            context.args = parts[1:] if len(parts) > 1 else []
            callback = self.callbacks.get("cookie")
            if callback:
                await callback(update, context)

    def build(self):
        if not settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        self.application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .concurrent_updates(True)
            .build()
        )

        # Saare commands jo controller.py mein hain + jo dynamic register honge
        default_commands = [
            "start",
            "status",
            "login",
            "otp",
            "cookie",
            "popup",
            "logout",
            "screen",
            "refresh",
            "help",
            "sniper",
            "stop_sniper",
            "trigger_buy",
            "heal",
        ]

        all_cmds = set(default_commands) | set(self.callbacks.keys())

        for command in all_cmds:
            self.application.add_handler(
                CommandHandler(
                    command,
                    self._create_handler(command),
                    block=False,
                )
            )

        # Document (.json cookie file) handler
        self.application.add_handler(
            MessageHandler(
                filters.Document.ALL,
                self._document_handler,
                block=False,
            )
        )

        return self.application

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
    ):
        if self.application is None:
            raise RuntimeError("Telegram application is not built")

        target_chat = chat_id or settings.telegram_chat_id
        if not target_chat:
            raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

        await self.application.bot.send_message(
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
            raise RuntimeError("Telegram application is not built")

        target_chat = chat_id or settings.telegram_chat_id
        if not target_chat:
            raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

        path = Path(photo_path)
        if not path.exists():
            raise FileNotFoundError(f"Screenshot not found: {photo_path}")

        with path.open("rb") as photo:
            await self.application.bot.send_photo(
                chat_id=target_chat,
                photo=photo,
                caption=caption,
            )

    async def start(self):
        if self.application is None:
            self.build()

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

    async def stop(self):
        if self.application is None:
            return

        if self.application.updater.running:
            await self.application.updater.stop()

        await self.application.stop()
        await self.application.shutdown()
