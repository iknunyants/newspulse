import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes, ConversationHandler

from newspulse.config import settings
from newspulse.db.repository import Repository
from newspulse.formatting import escape_md as _esc
from newspulse.matching.keywords import generate_keywords

logger = logging.getLogger(__name__)

# ConversationHandler state
WAITING_FOR_TOPIC = 0

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ Add Topic"), KeyboardButton("📋 My Topics")],
        [KeyboardButton("❌ Remove Topic")],
    ],
    resize_keyboard=True,
)

WELCOME = (
    "👋 Welcome to *NewsPulse*\\!\n\n"
    "I monitor news sources and send you articles matching your topics\\.\n\n"
    "Use the buttons below or these commands:\n"
    "/add\\_topic \\<description\\> — Add a topic to monitor\n"
    "/list\\_topics — Show your active topics\n"
    "/remove\\_topic — Remove a topic\n"
    "/help — Show this message"
)

HELP = WELCOME


def _get_repo(context: ContextTypes.DEFAULT_TYPE) -> Repository:
    return context.bot_data["repo"]


def _post_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 View Topics", callback_data="action:list_topics"),
            InlineKeyboardButton("➕ Add Another", callback_data="action:add_topic"),
        ]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    await repo.get_or_create_user(update.effective_user.id)
    await update.message.reply_text(WELCOME, parse_mode="MarkdownV2", reply_markup=MAIN_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode="MarkdownV2", reply_markup=MAIN_KEYBOARD)


async def _do_add_topic(
    topic_text: str,
    user_telegram_id: int,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(user_telegram_id)

    count = await repo.count_active_topics(user.id)
    if count >= settings.max_topics_per_user:
        await context.bot.send_message(
            chat_id,
            f"You already have {count} active topics \\(max {settings.max_topics_per_user}\\)\\. "
            "Remove one with /remove\\_topic first\\.",
            parse_mode="MarkdownV2",
        )
        return

    await context.bot.send_message(chat_id, "⏳ Adding your topic…")

    keywords = await generate_keywords(topic_text)
    topic = await repo.add_topic(user.id, topic_text, keywords)

    await context.bot.send_message(
        chat_id,
        f"✅ Topic added: *{_esc(topic.topic_text)}*",
        parse_mode="MarkdownV2",
        reply_markup=_post_action_keyboard(),
    )


async def add_topic_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the add_topic conversation."""
    # Handle keyboard button press (no args) or /add_topic with args
    topic_text = " ".join(context.args).strip() if context.args else ""

    if topic_text:
        await _do_add_topic(
            topic_text,
            update.effective_user.id,
            update.effective_chat.id,
            context,
        )
        return ConversationHandler.END

    await update.message.reply_text("What topic would you like to monitor?")
    return WAITING_FOR_TOPIC


async def add_topic_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the topic text after prompting."""
    topic_text = update.message.text.strip()
    if topic_text:
        await _do_add_topic(
            topic_text,
            update.effective_user.id,
            update.effective_chat.id,
            context,
        )
    return ConversationHandler.END


async def add_topic_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Topic addition cancelled\\.", parse_mode="MarkdownV2")
    return ConversationHandler.END


async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    topics = await repo.get_active_topics(user.id)

    add_button = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ Add Topic", callback_data="action:add_topic"),
    ]])

    if not topics:
        await update.message.reply_text(
            "You have no active topics\\. Use /add\\_topic to add one\\.",
            parse_mode="MarkdownV2",
            reply_markup=add_button,
        )
        return

    lines = ["*Your active topics:*\n"]
    for i, t in enumerate(topics, 1):
        lines.append(f"{i}\\. {_esc(t.topic_text)}")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=add_button,
    )


async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    topics = await repo.get_active_topics(user.id)

    if not topics:
        await update.message.reply_text(
            "You have no active topics to remove\\.",
            parse_mode="MarkdownV2",
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"{i}. {t.topic_text[:50]}", callback_data=f"remove:{t.id}")]
        for i, t in enumerate(topics, 1)
    ]
    await update.message.reply_text(
        "Which topic do you want to remove?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def remove_topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("remove:"):
        return

    topic_id = int(query.data.split(":")[1])
    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)

    removed = await repo.deactivate_topic(topic_id, user.id)
    if removed:
        await query.edit_message_text(
            "✅ Topic removed\\.",
            parse_mode="MarkdownV2",
            reply_markup=_post_action_keyboard(),
        )
    else:
        await query.edit_message_text(
            "Topic not found or already removed\\.", parse_mode="MarkdownV2"
        )


async def free_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return

    # If user was directed here by "Add Another" post-action button
    if context.user_data.get("awaiting_topic"):
        context.user_data.pop("awaiting_topic")
        await _do_add_topic(text, update.effective_user.id, update.effective_chat.id, context)
        return

    # Show confirmation dialog
    context.user_data["pending_topic"] = text
    display = text[:80] + "…" if len(text) > 80 else text
    await update.message.reply_text(
        f"Add *{_esc(display)}* as a topic?",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes", callback_data="confirm_add:yes"),
                InlineKeyboardButton("No", callback_data="confirm_add:no"),
            ]
        ]),
    )


async def confirm_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_add:yes":
        topic_text = context.user_data.pop("pending_topic", None)
        if not topic_text:
            await query.edit_message_text(
                "Session expired, please try again\\.", parse_mode="MarkdownV2"
            )
            return
        await query.edit_message_text("⏳ Adding your topic…")
        await _do_add_topic(topic_text, query.from_user.id, query.message.chat_id, context)
    else:
        context.user_data.pop("pending_topic", None)
        await query.edit_message_text("OK, not added\\.", parse_mode="MarkdownV2")


async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "action:list_topics":
        repo = _get_repo(context)
        user = await repo.get_or_create_user(query.from_user.id)
        topics = await repo.get_active_topics(user.id)

        add_button = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add Topic", callback_data="action:add_topic"),
        ]])

        if not topics:
            await context.bot.send_message(
                chat_id,
                "You have no active topics\\. Use /add\\_topic to add one\\.",
                parse_mode="MarkdownV2",
                reply_markup=add_button,
            )
        else:
            lines = ["*Your active topics:*\n"]
            for i, t in enumerate(topics, 1):
                lines.append(f"{i}\\. {_esc(t.topic_text)}")
            await context.bot.send_message(
                chat_id,
                "\n".join(lines),
                parse_mode="MarkdownV2",
                reply_markup=add_button,
            )

    elif query.data == "action:add_topic":
        context.user_data["awaiting_topic"] = True
        await context.bot.send_message(chat_id, "What topic would you like to monitor?")
