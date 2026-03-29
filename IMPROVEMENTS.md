# NewsPulse Improvements Checklist

## Status Overview

### A. User Interaction

| # | Feature | Status |
|---|---------|--------|
| A1 | Topic Pause/Resume | ✅ Done |
| A2 | Digest Mode | ✅ Done |
| A3 | Article Feedback Buttons | ✅ Done |
| A4 | Topic Suggestions | ☐ Pending |
| A5 | Search Past Articles | ☐ Pending |
| A6 | Statistics Command | ✅ Done |
| A7 | Quiet Hours | ☐ Pending |
| A8 | Reactivate Topics on Return | ✅ Done |

### B. Backend / Pipeline

| # | Feature | Status |
|---|---------|--------|
| B1 | Concurrent RSS Fetching | ✅ Done |
| B2 | Article Expiry | ✅ Done |
| B3 | Cross-Topic LLM Batching | ✅ Done |
| B4 | Fix Repository Abstraction Leaks | ✅ Done |
| B5 | Remove Phantom Russian Language | ✅ Done |
| B6 | Add Database Indexes | ✅ Done |
| B7 | Batch DB Commits | ☐ Pending |
| B8 | Keyword Refresh | ☐ Pending |

### C. Observability & Reliability

| # | Feature | Status |
|---|---------|--------|
| C1 | Structured Logging with Metrics | ☐ Pending |
| C2 | Admin Health Command | ☐ Pending |
| C3 | Source Failure Alerting | ☐ Pending |

### D. Testing

| # | Feature | Status |
|---|---------|--------|
| D1 | Unit Tests for Core Logic | ✅ Done |
| D2 | Scheduler Pipeline Test | ☐ Pending |

**12 done, 8 pending.**

---

## A. User Interaction

- [x] **A1. Topic Pause/Resume** — `/pause_topic` and `/resume_topic` commands let users temporarily mute a topic without deleting it. Paused topics are excluded from the matching pipeline and shown with a ⏸ indicator in topic lists.

- [x] **A2. Digest Mode** — Instead of real-time per-article notifications, users can opt into a daily digest delivered at a chosen hour. Articles are still matched every 15 minutes but queued and sent as one bundled message, reducing notification noise.

- [x] **A3. Article Feedback Buttons** — Each notification includes 👍/👎 inline buttons. Feedback is stored in an `article_feedback` table and can later be used to tune keyword lists or LLM prompts per user.

- [ ] **A4. Topic Suggestions** — After `/start`, suggest popular or trending topics based on what other users track or what's frequent in recent articles. Helps new users get started quickly.

- [ ] **A5. Search Past Articles** — A `/search <query>` command that searches already-scraped articles using SQLite FTS5 full-text search. Returns top 5 matches with links.

- [x] **A6. Statistics Command** — `/stats` shows per-topic article match counts for the last 7 days plus total articles scraped. Gives users confidence the bot is working and helps them tune topics.

- [ ] **A7. Quiet Hours** — Users set a "do not disturb" window (e.g., 11pm–8am). Notifications during that window are queued and delivered when it opens.

- [x] **A8. Reactivate Topics on Return** — When a user who previously blocked the bot returns via `/start`, all their deactivated topics are automatically reactivated with a welcome-back message.

## B. Backend / Pipeline

- [x] **B1. Concurrent RSS Fetching** — RSS feeds are now fetched in parallel via `asyncio.gather` instead of sequentially, significantly reducing scrape cycle time.

- [x] **B2. Article Expiry** — Articles older than 30 days are automatically deleted (along with their `sent_articles` records) at the end of each scrape cycle, preventing unbounded database growth.

- [x] **B3. Cross-Topic LLM Batching** — Group relevance checks by article instead of by topic. If one article matches keywords for 5 topics, ask the LLM once "is this relevant to topics A, B, C, D, E?" instead of 5 separate calls. Cuts LLM costs proportionally to topic overlap.

- [x] **B4. Fix Repository Abstraction Leaks** — Moved raw SQL from `scheduler.py` into proper repository methods (`get_telegram_id`, `deactivate_all_topics`). All DB access now goes through the repository.

- [x] **B5. Remove Phantom Russian Language** — Removed "ru" from default user languages since no Russian sources exist and it's not in `SUPPORTED_LANGUAGES`.

- [x] **B6. Add Database Indexes** — Added indexes on `topics(user_id, active)`, `articles(source)`, `articles(created_at)`, and `sent_articles(article_id/topic_id)` for query performance at scale.

- [ ] **B7. Batch DB Commits** — Wrap the article-storage and notification-send phases in explicit transactions instead of committing after each individual insert. Reduces I/O overhead during scrape cycles.

- [ ] **B8. Keyword Refresh** — Periodically regenerate keywords for long-lived topics so they stay current with evolving events. Could also trigger on negative feedback from A3.

## C. Observability & Reliability

- [ ] **C1. Structured Logging with Metrics** — Add counters for articles scraped per source, keyword matches, LLM calls, notifications sent, and errors. Log as structured JSON for easy aggregation.

- [ ] **C2. Admin Health Command** — An admin-only `/health` command showing last scrape time per source, articles scraped in last cycle, and any recent errors. Useful for the bot operator.

- [ ] **C3. Source Failure Alerting** — If a source fails to return articles for N consecutive cycles, log a warning or notify the admin. CSS-selector scrapers break silently on site redesigns.

## D. Testing

- [x] **D1. Unit Tests for Core Logic** — Added unit tests for repository CRUD, keyword matching, pause/resume, feedback, stats, and article expiry (36 tests total).

- [ ] **D2. Scheduler Pipeline Test** — End-to-end test of `scrape_and_notify` with mocked scrapers and mocked Telegram API, verifying the full scrape → store → match → notify flow.
