from pathlib import Path

from .config import settings


class SessionManager:
    def __init__(self):
        self.base_dir = Path(settings.sessions_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def session_path(self, slot_id: str) -> Path:
        path = self.base_dir / slot_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def delete_session(self, slot_id: str) -> None:
        path = self.base_dir / slot_id

        if not path.exists():
            return

        for item in path.rglob("*"):
            if item.is_file():
                item.unlink()

        for item in sorted(path.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()

        path.rmdir()
