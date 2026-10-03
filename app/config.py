import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    product_url: str = os.getenv(
        "PRODUCT_URL",
        "https://shop.rooter.gg/product/playstation-gift-cards",
    )

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Konsi service chal rahi hai (1 se 5 tak)
    current_service_id: int = int(os.getenv("CURRENT_SERVICE_ID", "1"))
    accounts_per_service: int = 5

    monitor_interval_seconds: int = 600
    recovery_delay_seconds: int = 5

    screenshots_dir: str = os.getenv(
        "SCREENSHOTS_DIR",
        "data/screenshots",
    )
    sessions_dir: str = os.getenv(
        "SESSIONS_DIR",
        "data/sessions",
    )

    @property
    def total_slots(self) -> int:
        return self.accounts_per_service

settings = Settings()
