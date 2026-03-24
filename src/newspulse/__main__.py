import asyncio
import logging
import signal

from newspulse.bot.app import create_app
from newspulse.config import settings
from newspulse.db.repository import Repository
from newspulse.scheduler import setup_scheduler


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting NewsPulse...")

    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    repo = await Repository.create(settings.database_path)

    app = create_app(settings, repo)
    scheduler = setup_scheduler(repo, app.bot, settings.scrape_interval_minutes)

    stop_event = asyncio.Event()

    def _handle_signal(*_) -> None:
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        scheduler.start()
        logger.info(
            "Bot running. Scraping every %d minutes.", settings.scrape_interval_minutes
        )
        await stop_event.wait()
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()

    await repo.close()
    logger.info("Goodbye.")


def main_sync() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
