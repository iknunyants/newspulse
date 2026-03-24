import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from newspulse.config import settings
from newspulse.db.repository import Repository
from newspulse.matching.keywords import generate_keywords

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Welcome to *NewsPulse*\\!\n\n"
    "I monitor news sources and send you articles matching your topics\\.\n\n"
    "*Commands:*\n"
    "/add\\_topic \\<description\\> — Add a topic to monitor\n"
    "/list\\_topics — Show your active topics\n"
    "/remove\\_topic — Remove a topic\n"
    "/help — Show this message"
)

HELP = WELCOME


def _get_repo(context: ContextTypes.DEFAULT_TYPE) -> Repository:
    return context.bot_data["repo"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    await repo.get_or_create_user(update.effective_user.id)
    await update.message.reply_text(WELCOME, parse_mode="MarkdownV2")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode="MarkdownV2")


async def add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)

    topic_text = " ".join(context.args).strip() if context.args else ""
    if not topic_text:
        await update.message.reply_text(
            "Please provide a topic description\\.\n"
            "Example: `/add_topic AI developments in Armenia`",
            parse_mode="MarkdownV2",
        )
        return

    count = await repo.count_active_topics(user.id)
    if count >= settings.max_topics_per_user:
        await update.message.reply_text(
            f"You already have {count} active topics \\(max {settings.max_topics_per_user}\\)\\. "
            "Remove one with /remove\\_topic first\\.",
            parse_mode="MarkdownV2",
        )
        return

    await update.message.reply_text("⏳ Generating keywords for your topic…")

    keywords = await generate_keywords(topic_text)
    topic = await repo.add_topic(user.id, topic_text, keywords)

    kw_list = "\\, ".join(_esc(k) for k in keywords[:15])
    await update.message.reply_text(
        f"✅ Topic added: *{_esc(topic.topic_text)}*\n\n"
        f"_Monitoring keywords:_ {kw_list}",
        parse_mode="MarkdownV2",
    )


async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    topics = await repo.get_active_topics(user.id)

    if not topics:
        await update.message.reply_text(
            "You have no active topics\\. Use /add\\_topic to add one\\.",
            parse_mode="MarkdownV2",
        )
        return

    lines = ["*Your active topics:*\n"]
    for i, t in enumerate(topics, 1):
        lines.append(f"{i}\\. {_esc(t.topic_text)}")
    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


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
        await query.edit_message_text("✅ Topic removed\\.", parse_mode="MarkdownV2")
    else:
        await query.edit_message_text(
            "Topic not found or already removed\\.", parse_mode="MarkdownV2"
        )


def _esc(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)
