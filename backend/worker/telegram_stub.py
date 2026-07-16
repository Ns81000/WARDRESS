"""Phase 0 stub for the dedicated Telegram bot container.

The real two-way bot (python-telegram-bot v22, commands /status /sites
/scan /ack /mute /help) is built in Phase 4. This stub exists so the
`telegram-bot` compose service starts cleanly and exits politely when
no token is configured.
"""

import logging
import os
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wardress.telegram")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log.info("TELEGRAM_BOT_TOKEN not set — bot idle. Configure it in Settings (Phase 4).")
    else:
        log.info("Token present — real bot arrives in Phase 4. Idling.")
    # Keep the container alive without busy-waiting; replaced by the
    # real Application.run_polling() loop in Phase 4.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
