# NewsPulse

A Telegram bot that monitors news sources and sends you articles matching your topics of interest.

## Features

- **Topic-based monitoring** — describe what you're interested in (e.g., "AI developments in Armenia") and get relevant articles delivered to your Telegram
- **Smart matching** — two-stage pipeline: fast keyword pre-filter + Gemini LLM relevance check
- **Multiple sources** — RSS feeds (BBC, Al Jazeera, CivilNet, 1Lurer) and web scraping (Hetq, Mediamax)
- **Multi-user** — anyone can use the bot with their own set of topics

## Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/add_topic <description>` | Add a topic to monitor |
| `/list_topics` | Show your active topics |
| `/remove_topic` | Remove a topic |
| `/help` | Show help |

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A Gemini API key (from [Google AI Studio](https://aistudio.google.com/apikey))

### Configuration

```bash
cp .env.example .env
```

Edit `.env` and fill in your tokens:

```
TELEGRAM_BOT_TOKEN=your_token_here
GEMINI_API_KEY=your_key_here
```

### Run locally

```bash
uv sync
uv run python -m newspulse
```

### Run with Docker

```bash
sudo docker compose up --build -d
```

View logs:

```bash
sudo docker compose logs -f
```

## How it works

1. Users add topics via `/add_topic` — Gemini generates relevant keywords for fast filtering
2. Every 15 minutes, the bot scrapes all configured news sources
3. New articles are matched against user topics in two stages:
   - **Keyword pre-filter** — fast, free check if article title/summary contains any topic keyword
   - **LLM relevance check** — Gemini confirms whether keyword-matched articles are actually relevant
4. Relevant articles are sent to the user's Telegram chat

## News sources

### RSS feeds
- BBC World News
- Al Jazeera
- CivilNet (Armenia)
- 1Lurer (Armenia)

### Web scraping
- Hetq (Armenia)
- Mediamax (Armenia)
