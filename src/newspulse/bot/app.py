import logging

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from newspulse.bot.handlers import (
    WAITING_FOR_TOPIC,
    action_callback,
    add_topic_cancel,
    add_topic_entry,
    add_topic_receive,
    confirm_add_callback,
    free_text_handler,
    help_command,
    list_topics,
    remove_topic,
    remove_topic_callback,
    start,
)
from newspulse.config import Settings
from newspulse.db.repository import Repository

logger = logging.getLogger(__name__)


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception in bot handler", exc_info=context.error)


def create_app(settings: Settings, repo: Repository) -> Application:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.bot_data["repo"] = repo

    # Keyboard button texts that should cancel the add_topic conversation
    _keyboard_buttons = filters.Regex("^(📋 My Topics|❌ Remove Topic)$")

    add_topic_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_topic", add_topic_entry),
            MessageHandler(filters.Regex("^➕ Add Topic$"), add_topic_entry),
        ],
        states={
            WAITING_FOR_TOPIC: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~_keyboard_buttons,
                    add_topic_receive,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", add_topic_cancel),
            MessageHandler(filters.COMMAND, add_topic_cancel),
            MessageHandler(_keyboard_buttons, add_topic_cancel),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(add_topic_conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 My Topics$"), list_topics))
    app.add_handler(MessageHandler(filters.Regex("^❌ Remove Topic$"), remove_topic))
    app.add_handler(CommandHandler("list_topics", list_topics))
    app.add_handler(CommandHandler("remove_topic", remove_topic))
    app.add_handler(CallbackQueryHandler(remove_topic_callback, pattern=r"^remove:"))
    app.add_handler(CallbackQueryHandler(confirm_add_callback, pattern=r"^confirm_add:"))
    app.add_handler(CallbackQueryHandler(action_callback, pattern=r"^action:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text_handler))
    app.add_error_handler(_error_handler)

    return app
