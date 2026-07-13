import os

import pytest

from coolhurst_booker.config import get_settings
from coolhurst_booker.db.repository import get_repository
from coolhurst_booker.jobs.scrape_job import run_scrape


@pytest.mark.integration
def test_live_scrape_once():
    settings = get_settings()
    if not settings.coolhurst_username or not settings.coolhurst_password:
        pytest.skip("COOLHURST_USERNAME/PASSWORD not configured")

    if os.environ.get("RUN_LIVE_SCRAPE") != "1":
        pytest.skip("Set RUN_LIVE_SCRAPE=1 to run live integration test")

    results = run_scrape(once=True)
    assert isinstance(results, dict)
    assert results.get("coolhurst") is None or results["coolhurst"] >= 0
    assert results.get("google") is None or results["google"] >= 0

    repo = get_repository(settings)
    summary = repo.get_summary()
    assert isinstance(summary, list)
