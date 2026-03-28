"""Unit tests for the database repository."""
from pathlib import Path

import pytest

from newspulse.db.repository import Repository


@pytest.fixture
async def repo(tmp_path: Path):
    r = await Repository.create(tmp_path / "test.db")
    yield r
    await r.close()


async def test_get_or_create_user(repo: Repository):
    user = await repo.get_or_create_user(12345)
    assert user.telegram_id == 12345
    assert user.id is not None

    # Same user returned on second call
    user2 = await repo.get_or_create_user(12345)
    assert user2.id == user.id


async def test_user_languages_default(repo: Repository):
    user = await repo.get_or_create_user(100)
    langs = await repo.get_user_languages(user.id)
    assert langs == ["en", "hy"]


async def test_set_user_languages(repo: Repository):
    user = await repo.get_or_create_user(100)
    await repo.set_user_languages(user.id, ["en"])
    langs = await repo.get_user_languages(user.id)
    assert langs == ["en"]


async def test_user_sources_default_none(repo: Repository):
    user = await repo.get_or_create_user(100)
    sources = await repo.get_user_sources(user.id)
    assert sources is None  # None means all sources


async def test_set_user_sources(repo: Repository):
    user = await repo.get_or_create_user(100)
    await repo.set_user_sources(user.id, ["BBC World", "Al Jazeera"])
    sources = await repo.get_user_sources(user.id)
    assert sources == ["BBC World", "Al Jazeera"]


async def test_add_topic(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "Armenian politics", ["Armenia", "politics"])
    assert topic.topic_text == "Armenian politics"
    assert topic.active is True
    assert topic.user_id == user.id


async def test_count_active_topics(repo: Repository):
    user = await repo.get_or_create_user(100)
    assert await repo.count_active_topics(user.id) == 0
    await repo.add_topic(user.id, "topic1", ["kw1"])
    assert await repo.count_active_topics(user.id) == 1
    await repo.add_topic(user.id, "topic2", ["kw2"])
    assert await repo.count_active_topics(user.id) == 2


async def test_deactivate_topic(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    assert await repo.deactivate_topic(topic.id, user.id) is True
    assert await repo.count_active_topics(user.id) == 0
    # Can't deactivate again
    assert await repo.deactivate_topic(topic.id, user.id) is False


async def test_reactivate_topics(repo: Repository):
    user = await repo.get_or_create_user(100)
    await repo.add_topic(user.id, "topic1", ["kw1"])
    await repo.add_topic(user.id, "topic2", ["kw2"])

    # Deactivate all
    deactivated = await repo.deactivate_all_topics(user.id)
    assert deactivated == 2
    assert await repo.count_active_topics(user.id) == 0

    # Reactivate all
    reactivated = await repo.reactivate_topics(user.id)
    assert reactivated == 2
    assert await repo.count_active_topics(user.id) == 2


async def test_reactivate_topics_no_topics(repo: Repository):
    user = await repo.get_or_create_user(100)
    reactivated = await repo.reactivate_topics(user.id)
    assert reactivated == 0


async def test_get_telegram_id(repo: Repository):
    user = await repo.get_or_create_user(99999)
    tid = await repo.get_telegram_id(user.id)
    assert tid == 99999


async def test_get_telegram_id_not_found(repo: Repository):
    tid = await repo.get_telegram_id(999)
    assert tid is None


async def test_upsert_article(repo: Repository):
    article, is_new = await repo.upsert_article(
        source="BBC World",
        title="Test Article",
        url="https://example.com/article-1",
        summary="A test summary.",
        published_at="2024-01-01",
    )
    assert is_new is True
    assert article.title == "Test Article"

    # Upsert same URL — not new
    article2, is_new2 = await repo.upsert_article(
        source="BBC World",
        title="Test Article",
        url="https://example.com/article-1",
        summary="A test summary.",
        published_at="2024-01-01",
    )
    assert is_new2 is False
    assert article2.id == article.id


async def test_article_sent_tracking(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    article, _ = await repo.upsert_article(
        source="Test", title="T", url="https://example.com/1",
        summary="S", published_at=None,
    )

    assert await repo.is_article_sent(article.id, topic.id) is False
    await repo.mark_article_sent(article.id, topic.id)
    assert await repo.is_article_sent(article.id, topic.id) is True


async def test_scrape_log(repo: Repository):
    assert await repo.get_last_scrape_time("BBC World") is None
    await repo.update_scrape_time("BBC World")
    assert await repo.get_last_scrape_time("BBC World") is not None


async def test_get_user_stats_empty(repo: Repository):
    user = await repo.get_or_create_user(100)
    stats = await repo.get_user_stats(user.id)
    assert stats == []


async def test_get_user_stats_with_data(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test topic", ["kw"])
    article, _ = await repo.upsert_article(
        source="Test", title="T", url="https://example.com/1",
        summary="S", published_at=None,
    )
    await repo.mark_article_sent(article.id, topic.id)

    stats = await repo.get_user_stats(user.id)
    assert len(stats) == 1
    assert stats[0] == ("test topic", 1)


async def test_get_total_articles_count(repo: Repository):
    assert await repo.get_total_articles_count() == 0
    await repo.upsert_article(
        source="Test", title="T", url="https://example.com/1",
        summary="S", published_at=None,
    )
    assert await repo.get_total_articles_count() == 1


async def test_pause_topic(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    assert topic.paused is False

    paused = await repo.pause_topic(topic.id, user.id)
    assert paused is True

    # Active topics (exclude paused) should be empty
    active = await repo.get_active_topics(user.id, include_paused=False)
    assert len(active) == 0

    # Active topics (include paused) should still have it
    all_active = await repo.get_active_topics(user.id, include_paused=True)
    assert len(all_active) == 1
    assert all_active[0].paused is True


async def test_resume_topic(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    await repo.pause_topic(topic.id, user.id)

    resumed = await repo.resume_topic(topic.id, user.id)
    assert resumed is True

    active = await repo.get_active_topics(user.id, include_paused=False)
    assert len(active) == 1
    assert active[0].paused is False


async def test_get_paused_topics(repo: Repository):
    user = await repo.get_or_create_user(100)
    t1 = await repo.add_topic(user.id, "topic1", ["kw1"])
    await repo.add_topic(user.id, "topic2", ["kw2"])
    await repo.pause_topic(t1.id, user.id)

    paused = await repo.get_paused_topics(user.id)
    assert len(paused) == 1
    assert paused[0].topic_text == "topic1"


async def test_pause_already_paused(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    await repo.pause_topic(topic.id, user.id)
    # Can't pause again
    assert await repo.pause_topic(topic.id, user.id) is False


async def test_resume_not_paused(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    # Can't resume if not paused
    assert await repo.resume_topic(topic.id, user.id) is False


async def test_save_feedback(repo: Repository):
    user = await repo.get_or_create_user(100)
    article, _ = await repo.upsert_article(
        source="Test", title="T", url="https://example.com/1",
        summary="S", published_at=None,
    )
    await repo.save_feedback(user.id, article.id, relevant=True)
    pos, neg = await repo.get_feedback_stats(user.id)
    assert pos == 1
    assert neg == 0


async def test_save_feedback_update(repo: Repository):
    """Updating feedback replaces the old value."""
    user = await repo.get_or_create_user(100)
    article, _ = await repo.upsert_article(
        source="Test", title="T", url="https://example.com/1",
        summary="S", published_at=None,
    )
    await repo.save_feedback(user.id, article.id, relevant=True)
    await repo.save_feedback(user.id, article.id, relevant=False)
    pos, neg = await repo.get_feedback_stats(user.id)
    assert pos == 0
    assert neg == 1


async def test_feedback_stats_empty(repo: Repository):
    user = await repo.get_or_create_user(100)
    pos, neg = await repo.get_feedback_stats(user.id)
    assert pos == 0
    assert neg == 0


async def test_digest_mode_default(repo: Repository):
    user = await repo.get_or_create_user(100)
    assert user.digest_mode is False
    assert user.digest_hour == 9


async def test_set_digest_mode(repo: Repository):
    user = await repo.get_or_create_user(100)
    await repo.set_digest_mode(user.id, enabled=True, hour=18)
    updated = await repo.get_user_by_id(user.id)
    assert updated.digest_mode is True
    assert updated.digest_hour == 18


async def test_get_users_for_digest(repo: Repository):
    user = await repo.get_or_create_user(100)
    await repo.set_digest_mode(user.id, enabled=True, hour=9)

    users_at_9 = await repo.get_users_for_digest(9)
    assert len(users_at_9) == 1
    assert users_at_9[0].id == user.id

    users_at_10 = await repo.get_users_for_digest(10)
    assert len(users_at_10) == 0


async def test_digest_queue_and_clear(repo: Repository):
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    article, _ = await repo.upsert_article(
        source="Test", title="T", url="https://example.com/1",
        summary="S", published_at=None,
    )

    await repo.queue_digest_article(user.id, article.id, topic.id)
    items = await repo.get_digest_queue(user.id)
    assert len(items) == 1
    assert items[0][0].id == article.id
    assert items[0][1][0].id == topic.id

    await repo.clear_digest_queue(user.id)
    items = await repo.get_digest_queue(user.id)
    assert len(items) == 0


async def test_digest_queue_groups_by_article(repo: Repository):
    """Multiple topics for the same article appear as one entry."""
    user = await repo.get_or_create_user(100)
    t1 = await repo.add_topic(user.id, "topic1", ["kw1"])
    t2 = await repo.add_topic(user.id, "topic2", ["kw2"])
    article, _ = await repo.upsert_article(
        source="Test", title="T", url="https://example.com/1",
        summary="S", published_at=None,
    )

    await repo.queue_digest_article(user.id, article.id, t1.id)
    await repo.queue_digest_article(user.id, article.id, t2.id)
    items = await repo.get_digest_queue(user.id)
    assert len(items) == 1  # One article
    assert len(items[0][1]) == 2  # Two topics


async def test_get_user_by_id(repo: Repository):
    user = await repo.get_or_create_user(100)
    fetched = await repo.get_user_by_id(user.id)
    assert fetched.id == user.id
    assert fetched.telegram_id == 100


async def test_get_user_by_id_not_found(repo: Repository):
    result = await repo.get_user_by_id(9999)
    assert result is None


async def test_delete_old_articles(repo: Repository):
    # Insert an article, then backdate it to 60 days ago
    article, _ = await repo.upsert_article(
        source="Test", title="Old", url="https://example.com/old",
        summary="S", published_at=None,
    )
    await repo._conn.execute(
        "UPDATE articles SET created_at = datetime('now', '-60 days') "
        "WHERE id = ?", (article.id,),
    )
    await repo._conn.commit()

    # Insert a recent article
    await repo.upsert_article(
        source="Test", title="New", url="https://example.com/new",
        summary="S", published_at=None,
    )

    deleted = await repo.delete_old_articles(days=30)
    assert deleted == 1
    assert await repo.get_total_articles_count(days=90) == 1


async def test_delete_old_articles_cascades_sent(repo: Repository):
    """Deleting old articles should also clean up sent_articles."""
    user = await repo.get_or_create_user(100)
    topic = await repo.add_topic(user.id, "test", ["kw"])
    article, _ = await repo.upsert_article(
        source="Test", title="Old", url="https://example.com/old",
        summary="S", published_at=None,
    )
    await repo.mark_article_sent(article.id, topic.id)

    # Backdate the article
    await repo._conn.execute(
        "UPDATE articles SET created_at = datetime('now', '-60 days') "
        "WHERE id = ?", (article.id,),
    )
    await repo._conn.commit()

    deleted = await repo.delete_old_articles(days=30)
    assert deleted == 1
    # sent_articles record should also be gone
    assert await repo.is_article_sent(article.id, topic.id) is False
