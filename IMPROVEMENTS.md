# NewsPulse Improvements Checklist

## A. User Interaction

- [ ] **A1. Topic Pause/Resume** — Temporarily mute topics without deleting
- [ ] **A2. Digest Mode** — Batched daily summaries instead of real-time notifications
- [ ] **A3. Article Feedback Buttons** — "Relevant"/"Not Relevant" under each notification
- [ ] **A4. Topic Suggestions** — Trending/popular topics for new users
- [ ] **A5. Search Past Articles** — `/search` command with SQLite FTS5
- [ ] **A6. Statistics Command** — `/stats` showing match counts per topic
- [ ] **A7. Quiet Hours** — Queue notifications during user-defined sleep window
- [ ] **A8. Reactivate Topics on Return** — Restore topics when blocked user sends `/start`

## B. Backend / Pipeline

- [ ] **B1. Concurrent RSS Fetching** — Parallel feed fetching with asyncio.gather
- [ ] **B2. Article Expiry** — Auto-delete articles older than 30 days
- [ ] **B3. Cross-Topic LLM Batching** — Batch relevance checks across topics
- [ ] **B4. Fix Repository Abstraction Leaks** — Move raw SQL from scheduler into repo
- [ ] **B5. Remove Phantom Russian Language** — Clean up dead "ru" default
- [ ] **B6. Add Database Indexes** — Index frequently queried columns
- [ ] **B7. Batch DB Commits** — Wrap scrape/send phases in transactions
- [ ] **B8. Keyword Refresh** — Periodically regenerate stale keywords

## C. Observability & Reliability

- [ ] **C1. Structured Logging with Metrics** — Counters for scrapes, matches, sends, errors
- [ ] **C2. Admin Health Command** — `/health` showing per-source scrape status
- [ ] **C3. Source Failure Alerting** — Warn on consecutive scraper failures

## D. Testing

- [ ] **D1. Unit Tests for Core Logic** — Keyword matching, relevance checking, repository CRUD
- [ ] **D2. Scheduler Pipeline Test** — End-to-end with mocked scrapers and Telegram API
