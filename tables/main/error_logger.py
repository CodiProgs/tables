import json
from datetime import datetime
from pathlib import Path

from django.conf import settings


def _log_dir() -> Path:
    log_dir = Path(settings.BASE_DIR) / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def write_error_log(source: str, data: dict) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        **data,
    }
    log_file = _log_dir() / f"errors_{datetime.now():%Y-%m-%d}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
