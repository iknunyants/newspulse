import json
import logging

import httpx
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
from newspulse.scrapers import (
    SOURCE_LANGUAGES,
    SUPPORTED_LANGUAGES,
    get_all_source_names,
    get_all_source_names_with_channels,
)
from newspulse.scrapers.telegram import fetch_channel_title, parse_channel_username

logger = logging.getLogger(__name__)

# ConversationHandler states
WAITING_FOR_TOPIC = 0
WAITING_FOR_CHANNEL = 1

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ Add Topic"), KeyboardButton("📋 My Topics")],
        [KeyboardButton("❌ Remove Topic"), KeyboardButton("📊 Stats")],
        [KeyboardButton("🌐 Languages"), KeyboardButton("📰 Sources")],
        [KeyboardButton("⏸ Pause Topic"), KeyboardButton("▶️ Resume Topic")],
        [KeyboardButton("📡 Add Channel"), KeyboardButton("📡 My Channels")],
        [KeyboardButton("📬 Digest"), KeyboardButton("❓ Help")],
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
    "/pause\\_topic — Pause a topic temporarily\n"
    "/resume\\_topic — Resume a paused topic\n"
    "/stats — Your topic match statistics\n"
    "/digest — Toggle daily digest mode\n"
    "/languages — Choose news languages\n"
    "/sources — Choose which news sources to follow\n"
    "/add\\_channel — Monitor a Telegram channel\n"
    "/list\\_channels — Show monitored channels\n"
    "/remove\\_channel — Stop monitoring a channel\n"
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


def _language_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    """Build the language toggle inline keyboard."""
    buttons = [
        InlineKeyboardButton(
            f"{'✅' if code in selected else '⬜'} {name}",
            callback_data=f"lang_toggle:{code}",
        )
        for code, name in SUPPORTED_LANGUAGES.items()
    ]
    done_row = [InlineKeyboardButton("Done ✓", callback_data="lang_done")]
    return InlineKeyboardMarkup([buttons, done_row])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)

    # Reactivate topics if user previously blocked the bot
    reactivated = await repo.reactivate_topics(user.id)
    if reactivated:
        await update.message.reply_text(
            f"🔄 Welcome back\\! Reactivated {reactivated} "
            f"topic{'s' if reactivated > 1 else ''}\\.",
            parse_mode="MarkdownV2",
        )

    await update.message.reply_text(WELCOME, parse_mode="MarkdownV2", reply_markup=MAIN_KEYBOARD)

    current = json.loads(user.languages_json)
    await update.message.reply_text(
        "🌐 *Choose your news languages:*\nYou'll only receive articles in selected languages\\.",
        parse_mode="MarkdownV2",
        reply_markup=_language_keyboard(current),
    )


async def languages_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the language selection keyboard."""
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    current = json.loads(user.languages_json)
    await update.message.reply_text(
        "🌐 *Choose your news languages:*\nYou'll only receive articles in selected languages\\.",
        parse_mode="MarkdownV2",
        reply_markup=_language_keyboard(current),
    )


async def lang_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a language on/off."""
    query = update.callback_query

    code = query.data.split(":", 1)[1]
    if code not in SUPPORTED_LANGUAGES:
        await query.answer()
        return

    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)
    current: list[str] = json.loads(user.languages_json)

    if code in current:
        if len(current) == 1:
            await query.answer("You must keep at least one language selected.", show_alert=True)
            return
        current.remove(code)
    else:
        current.append(code)

    await repo.set_user_languages(user.id, current)
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=_language_keyboard(current))


async def lang_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm language selection."""
    query = update.callback_query
    await query.answer()

    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)
    current: list[str] = json.loads(user.languages_json)
    names = ", ".join(SUPPORTED_LANGUAGES[c] for c in current if c in SUPPORTED_LANGUAGES)
    await query.edit_message_text(
        f"✅ Languages set: *{_esc(names)}*",
        parse_mode="MarkdownV2",
    )


def _source_keyboard(
    all_sources: list[str], selected: list[str] | None
) -> InlineKeyboardMarkup:
    """Build the source toggle inline keyboard, grouped by language, with Telegram section."""
    by_lang: dict[str, list[str]] = {}
    tg_sources: list[str] = []
    for name in all_sources:
        if name.startswith("tg:"):
            tg_sources.append(name)
        else:
            lang = SOURCE_LANGUAGES.get(name, "en")
            by_lang.setdefault(lang, []).append(name)

    def _checked(s: str) -> str:
        on = selected is None or s in selected
        return "✅" if on else "⬜"

    rows: list[list[InlineKeyboardButton]] = []
    for lang_code, lang_name in SUPPORTED_LANGUAGES.items():
        sources_in_lang = by_lang.get(lang_code, [])
        if not sources_in_lang:
            continue
        rows.append([InlineKeyboardButton(f"── {lang_name} ──", callback_data="src_noop")])
        for i in range(0, len(sources_in_lang), 2):
            pair = sources_in_lang[i:i + 2]
            rows.append([
                InlineKeyboardButton(
                    f"{_checked(s)} {s}", callback_data=f"src_toggle:{s}"
                )
                for s in pair
            ])

    if tg_sources:
        rows.append([InlineKeyboardButton("── 📡 Channels ──", callback_data="src_noop")])
        for i in range(0, len(tg_sources), 2):
            pair = tg_sources[i:i + 2]
            rows.append([
                InlineKeyboardButton(
                    f"{_checked(s)} @{s[3:]}",
                    callback_data=f"src_toggle:{s}",
                )
                for s in pair
            ])

    rows.append([InlineKeyboardButton("Done ✓", callback_data="src_done")])
    return InlineKeyboardMarkup(rows)


async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the source selection keyboard."""
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    current = await repo.get_user_sources(user.id)
    all_sources = await get_all_source_names_with_channels(repo)
    await update.message.reply_text(
        "📰 *Choose your news sources:*\nYou'll only receive articles from selected sources\\.",
        parse_mode="MarkdownV2",
        reply_markup=_source_keyboard(all_sources, current),
    )


async def src_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a source on/off."""
    query = update.callback_query

    source_name = query.data.split(":", 1)[1]
    repo = _get_repo(context)
    all_sources = await get_all_source_names_with_channels(repo)
    if source_name not in all_sources:
        await query.answer()
        return

    user = await repo.get_or_create_user(query.from_user.id)
    raw = await repo.get_user_sources(user.id)
    static_sources = get_all_source_names()
    current: list[str] = list(static_sources) if raw is None else list(raw)

    if source_name in current:
        if len(current) == 1:
            await query.answer("You must keep at least one source selected.", show_alert=True)
            return
        current.remove(source_name)
    else:
        current.append(source_name)

    # Store NULL only if exactly the static (non-Telegram) sources are all selected
    tg_in_current = [s for s in current if s.startswith("tg:")]
    static_in_current = [s for s in current if not s.startswith("tg:")]
    if not tg_in_current and set(static_in_current) == set(static_sources):
        new_value: list[str] | None = None
    else:
        new_value = current
    await repo.set_user_sources(user.id, new_value)
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=_source_keyboard(all_sources, new_value))


async def src_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm source selection."""
    query = update.callback_query
    await query.answer()

    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)
    current = await repo.get_user_sources(user.id)
    static_names = get_all_source_names()
    if current is None:
        display_names = static_names
    else:
        display_names = [
            f"@{s[3:]}" if s.startswith("tg:") else s for s in current
        ]
    names = ", ".join(display_names)
    await query.edit_message_text(
        f"✅ Sources set: *{_esc(names)}*",
        parse_mode="MarkdownV2",
    )


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
    topics = await repo.get_active_topics(user.id, include_paused=True)

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
        status = " ⏸" if t.paused else ""
        lines.append(f"{i}\\. {_esc(t.topic_text)}{status}")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=add_button,
    )


async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    topics = await repo.get_active_topics(user.id, include_paused=True)

    if not topics:
        await update.message.reply_text(
            "You have no active topics to remove\\.",
            parse_mode="MarkdownV2",
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            f"{i}. {t.topic_text[:50]}{'  ⏸' if t.paused else ''}",
            callback_data=f"remove:{t.id}",
        )]
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


async def pause_topic_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show active (non-paused) topics for pausing."""
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    topics = await repo.get_active_topics(user.id, include_paused=False)

    if not topics:
        await update.message.reply_text(
            "You have no active topics to pause\\.",
            parse_mode="MarkdownV2",
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            f"⏸ {t.topic_text[:50]}", callback_data=f"pause:{t.id}"
        )]
        for t in topics
    ]
    await update.message.reply_text(
        "Which topic do you want to pause?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def resume_topic_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show paused topics for resuming."""
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    paused = await repo.get_paused_topics(user.id)

    if not paused:
        await update.message.reply_text(
            "You have no paused topics\\.",
            parse_mode="MarkdownV2",
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            f"▶ {t.topic_text[:50]}", callback_data=f"resume:{t.id}"
        )]
        for t in paused
    ]
    await update.message.reply_text(
        "Which topic do you want to resume?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def pause_topic_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    topic_id = int(query.data.split(":")[1])
    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)

    paused = await repo.pause_topic(topic_id, user.id)
    if paused:
        await query.edit_message_text(
            "⏸ Topic paused\\. Use /resume\\_topic to resume it\\.",
            parse_mode="MarkdownV2",
            reply_markup=_post_action_keyboard(),
        )
    else:
        await query.edit_message_text(
            "Topic not found or already paused\\.",
            parse_mode="MarkdownV2",
        )


async def resume_topic_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    topic_id = int(query.data.split(":")[1])
    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)

    resumed = await repo.resume_topic(topic_id, user.id)
    if resumed:
        await query.edit_message_text(
            "▶ Topic resumed\\!",
            parse_mode="MarkdownV2",
            reply_markup=_post_action_keyboard(),
        )
    else:
        await query.edit_message_text(
            "Topic not found or not paused\\.",
            parse_mode="MarkdownV2",
        )


async def feedback_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle article feedback (thumbs up/down)."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    relevant = parts[1] == "1"
    article_id = int(parts[2])

    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)
    await repo.save_feedback(user.id, article_id, relevant)

    label = "👍 Relevant" if relevant else "👎 Not relevant"
    # Remove the feedback buttons; preserve the original message formatting
    await query.answer(label)
    await query.edit_message_reply_markup(reply_markup=None)


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
        topics = await repo.get_active_topics(user.id, include_paused=True)

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
                status = " ⏸" if t.paused else ""
                lines.append(f"{i}\\. {_esc(t.topic_text)}{status}")
            await context.bot.send_message(
                chat_id,
                "\n".join(lines),
                parse_mode="MarkdownV2",
                reply_markup=add_button,
            )

    elif query.data == "action:add_topic":
        context.user_data["awaiting_topic"] = True
        await context.bot.send_message(
            chat_id, "What topic would you like to monitor?"
        )


def _digest_keyboard(enabled: bool, hour: int) -> InlineKeyboardMarkup:
    """Inline keyboard for digest mode toggle and hour selection."""
    toggle_label = "✅ Digest ON — turn off" if enabled else "⬜ Digest OFF — turn on"
    rows = [
        [InlineKeyboardButton(toggle_label, callback_data="digest_toggle")],
    ]
    if enabled:
        # Hour selection: show a row of quick-pick hours
        rows.append([
            InlineKeyboardButton(
                f"{'▶' if h == hour else ''}{h:02d}:00 UTC",
                callback_data=f"digest_hour:{h}",
            )
            for h in [6, 9, 12, 18, 21]
        ])
    rows.append([InlineKeyboardButton("Done ✓", callback_data="digest_done")])
    return InlineKeyboardMarkup(rows)


async def digest_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Toggle digest mode and choose delivery hour."""
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    status = "ON" if user.digest_mode else "OFF"
    await update.message.reply_text(
        f"📬 *Digest mode is currently {_esc(status)}*\n\n"
        "In digest mode you receive one daily summary instead of real\\-time "
        "notifications\\. Choose your preferred delivery hour in UTC\\.",
        parse_mode="MarkdownV2",
        reply_markup=_digest_keyboard(user.digest_mode, user.digest_hour),
    )


async def digest_toggle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)
    new_mode = not user.digest_mode
    await repo.set_digest_mode(user.id, new_mode, user.digest_hour)
    await query.edit_message_reply_markup(
        reply_markup=_digest_keyboard(new_mode, user.digest_hour)
    )


async def digest_hour_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    hour = int(query.data.split(":")[1])
    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)
    await repo.set_digest_mode(user.id, user.digest_mode, hour)
    await query.edit_message_reply_markup(
        reply_markup=_digest_keyboard(user.digest_mode, hour)
    )


async def digest_done_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)
    if user.digest_mode:
        msg = (
            f"✅ Digest mode ON — you'll receive a daily summary at "
            f"*{user.digest_hour:02d}:00 UTC*\\."
        )
    else:
        msg = "⬜ Digest mode OFF — you'll receive real\\-time notifications\\."
    await query.edit_message_text(msg, parse_mode="MarkdownV2")


async def stats_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show per-topic match statistics for the last 7 days."""
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)

    topic_stats = await repo.get_user_stats(user.id, days=7)
    total = await repo.get_total_articles_count(days=7)

    if not topic_stats:
        await update.message.reply_text(
            "You have no active topics\\. Use /add\\_topic to add one\\.",
            parse_mode="MarkdownV2",
        )
        return

    lines = ["*📊 Your stats \\(last 7 days\\):*\n"]
    for topic_text, count in topic_stats:
        lines.append(f"• {_esc(topic_text)}: *{count}* match{'es' if count != 1 else ''}")
    lines.append(f"\n📰 Total articles scraped: *{total}*")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# Telegram channel monitoring
# ---------------------------------------------------------------------------

async def add_channel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📡 Send the Telegram channel link or \\@handle\\.\n\n"
        "Examples: `t\\.me/bbcnews`, `@bbcnews`, `bbcnews`\n\n"
        "Send /cancel to abort\\.",
        parse_mode="MarkdownV2",
    )
    return WAITING_FOR_CHANNEL


async def add_channel_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    username = parse_channel_username(text)
    if not username:
        await update.message.reply_text(
            "❌ Invalid format\\. Please send a link like `t\\.me/name` or `@name`\\.",
            parse_mode="MarkdownV2",
        )
        return WAITING_FOR_CHANNEL

    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)

    # Check per-user channel limit
    user_channels = await repo.list_channels_added_by(user.id)
    if len(user_channels) >= settings.max_channels_per_user:
        await update.message.reply_text(
            f"You already manage {len(user_channels)} channels "
            f"\\(max {settings.max_channels_per_user}\\)\\. "
            "Remove one with /remove\\_channel first\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    source_key = f"tg:{username}"

    # If channel already exists and is active, just subscribe the user to it
    existing = await repo.get_telegram_channel_by_username(username)
    if existing and existing.active:
        user_sources = await repo.get_user_sources(user.id)
        static_names = get_all_source_names()
        sources: list[str] = list(static_names) if user_sources is None else list(user_sources)
        if source_key not in sources:
            sources.append(source_key)
            await repo.set_user_sources(user.id, sources)
        await update.message.reply_text(
            f"✅ Now monitoring *{_esc(existing.title)}* \\(@{_esc(username)}\\)\\.\n"
            "Posts matching your topics will arrive within 15 minutes\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    # Validate the channel by fetching its preview page
    await update.message.reply_text("⏳ Validating channel…")
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        title = await fetch_channel_title(username, client)

    if not title:
        await update.message.reply_text(
            "❌ Channel not found, is private, or has preview disabled\\.\n"
            "Only public channels with web previews can be monitored\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    await repo.add_telegram_channel(username, title, user.id)

    user_sources = await repo.get_user_sources(user.id)
    static_names = get_all_source_names()
    sources = list(static_names) if user_sources is None else list(user_sources)
    if source_key not in sources:
        sources.append(source_key)
        await repo.set_user_sources(user.id, sources)

    await update.message.reply_text(
        f"✅ Channel added: *{_esc(title)}* \\(@{_esc(username)}\\)\\.\n\n"
        "Posts matching your topics will be monitored every 15 minutes\\.\n"
        "Use /list\\_channels to manage channels or toggle forward\\-all mode\\.",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


async def add_channel_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Channel addition cancelled\\.", parse_mode="MarkdownV2")
    return ConversationHandler.END


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    channels = await repo.get_active_telegram_channels()
    user_sources = await repo.get_user_sources(user.id)
    subscribed: set[str] = (
        set(user_sources) if user_sources is not None else set()
    )

    if not channels:
        await update.message.reply_text(
            "No Telegram channels are being monitored yet\\. "
            "Use /add\\_channel to add one\\.",
            parse_mode="MarkdownV2",
        )
        return

    rows: list[list[InlineKeyboardButton]] = []
    lines = ["*📡 Monitored Telegram channels:*\n"]
    for ch in channels:
        source_key = f"tg:{ch.username}"
        is_mine = ch.added_by_user_id == user.id
        is_subscribed = source_key in subscribed
        mode = await repo.get_user_channel_mode(user.id, ch.id)

        label = f"@{ch.username} — {ch.title}"
        if is_mine:
            label += " \\(yours\\)"
        lines.append(_esc(label))

        btns: list[InlineKeyboardButton] = []
        if is_subscribed:
            mode_label = "✅ Forward all" if mode == "forward_all" else "⬜ Forward all"
            btns.append(InlineKeyboardButton(mode_label, callback_data=f"ch_mode:{ch.id}"))
        if is_mine:
            btns.append(InlineKeyboardButton("🗑 Remove", callback_data=f"ch_remove:{ch.id}"))
        if btns:
            rows.append(btns)

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(rows) if rows else None,
    )


async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _get_repo(context)
    user = await repo.get_or_create_user(update.effective_user.id)
    channels = await repo.list_channels_added_by(user.id)

    if not channels:
        await update.message.reply_text(
            "You have no channels to remove\\. "
            "Only channels you added can be removed\\.",
            parse_mode="MarkdownV2",
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            f"🗑 @{ch.username} — {ch.title[:40]}",
            callback_data=f"ch_remove:{ch.id}",
        )]
        for ch in channels
    ]
    await update.message.reply_text(
        "Which channel do you want to remove?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def channel_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle forward_all / filter mode for a channel."""
    query = update.callback_query
    await query.answer()

    channel_id = int(query.data.split(":")[1])
    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)

    current_mode = await repo.get_user_channel_mode(user.id, channel_id)
    new_mode = "filter" if current_mode == "forward_all" else "forward_all"
    await repo.set_user_channel_mode(user.id, channel_id, new_mode)

    if new_mode == "forward_all":
        msg = (
            "✅ *Forward\\-all mode ON* — every post from this channel will be "
            "delivered to you unfiltered\\."
        )
    else:
        msg = (
            "⬜ *Forward\\-all mode OFF* — only posts matching your topics will be delivered\\."
        )
    await query.answer(
        "Forward-all ON" if new_mode == "forward_all" else "Filter mode ON",
        show_alert=False,
    )
    await query.edit_message_text(msg, parse_mode="MarkdownV2")


async def channel_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a channel (only the adder can do this)."""
    query = update.callback_query
    await query.answer()

    channel_id = int(query.data.split(":")[1])
    repo = _get_repo(context)
    user = await repo.get_or_create_user(query.from_user.id)

    # Fetch channel and verify ownership
    channels = await repo.get_active_telegram_channels()
    channel = next((ch for ch in channels if ch.id == channel_id), None)
    if not channel or channel.added_by_user_id != user.id:
        await query.edit_message_text(
            "Channel not found or you are not the owner\\.", parse_mode="MarkdownV2"
        )
        return

    source_key = f"tg:{channel.username}"

    # Deactivate the channel
    await repo.deactivate_telegram_channel(channel.username)

    # Remove source key from all users' sources_json
    async with repo._conn.execute(
        "SELECT id, sources_json FROM users WHERE sources_json IS NOT NULL"
    ) as cur:
        user_rows = await cur.fetchall()
    for row in user_rows:
        srcs = json.loads(row["sources_json"])
        if source_key in srcs:
            srcs.remove(source_key)
            await repo.set_user_sources(row["id"], srcs if srcs else None)

    await query.edit_message_text(
        f"✅ Channel *@{_esc(channel.username)}* removed\\.",
        parse_mode="MarkdownV2",
    )
