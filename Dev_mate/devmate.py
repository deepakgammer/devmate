import logging
import logging.handlers
import sys
from pathlib import Path

# ─── Add project root to path ────────────────────────────────────────────────
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

import config

# Bootstrap data directory & logging BEFORE importing modules
config.DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging Setup ─────────────────────────────────────────────────────────────
def _setup_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Rotating file handler
    fh = logging.handlers.RotatingFileHandler(
        config.LOG_PATH,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root_logger.addHandler(fh)

    # Console handler (minimal)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root_logger.addHandler(ch)

_setup_logging()

# ── Import controller AFTER logging is configured ─────────────────────────────
from modules.controller import DevMateController


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    controller = DevMateController()
    controller.run()
