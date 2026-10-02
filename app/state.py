from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class AccountState:
    slot_id: str

    phone_number: Optional[str] = None
    logged_in: bool = False
    active: bool = False

    current_page: str = "unknown"
    last_error: Optional[str] = None
    last_screenshot: Optional[str] = None

    wallet_balance: Optional[float] = None
    last_order_id: Optional[str] = None

    updated_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    def update(self, **changes) -> None:
        for key, value in changes.items():
            if hasattr(self, key):
                setattr(self, key, value)

        self.updated_at = datetime.utcnow().isoformat()
