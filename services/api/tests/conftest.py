import pytest

from app.store import job_store


@pytest.fixture(autouse=True)
def clean_store():
    job_store.clear()
    yield
    job_store.clear()
