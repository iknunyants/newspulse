from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler

from newspulse.bot.handlers import (
    add_topic,
    help_command,
    list_topics,
    remove_topic,
    remove_topic_callback,
    start,
)
from newspulse.config import Settings
from newspulse.db.repository import Repository


def create_app(settings: Settings, repo: Repository) -> Application:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.bot_data["repo"] = repo

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add_topic", add_topic))
    app.add_handler(CommandHandler("list_topics", list_topics))
    app.add_handler(CommandHandler("remove_topic", remove_topic))
    app.add_handler(CallbackQueryHandler(remove_topic_callback, pattern=r"^remove:"))

    return app
