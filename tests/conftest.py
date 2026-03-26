import asyncio

import httpx
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: marks tests that hit live external URLs (deselect with -m 'not live')",
    )


@pytest.fixture(autouse=True)
def reset_fetch_semaphore():
    """Recreate the module-level asyncio.Semaphore in web.py before each test.

    The semaphore is created at import time and binds to the first event loop.
    With per-function event loops (pytest-asyncio default) it must be reset so
    each test gets a semaphore bound to its own loop.
    """
    import newspulse.scrapers.web as web_mod
    web_mod._FETCH_SEMAPHORE = asyncio.Semaphore(5)


@pytest.fixture
async def http_client():
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        yield client
