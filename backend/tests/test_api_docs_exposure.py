"""The interactive API docs are off in production (security review F-4, defect D-12; owner Siddh). No database."""

import pytest

from main import api_docs_settings


def test_production_turns_off_every_docs_route():
    assert api_docs_settings("production") == {"docs_url": None, "redoc_url": None, "openapi_url": None}


@pytest.mark.parametrize("env", ["development", "staging"])
def test_development_and_staging_keep_the_docs(env):
    assert api_docs_settings(env) == {}


def test_docs_answer_outside_production(client):
    # The test app runs with APP_ENV=development.
    assert client.get("/openapi.json").status_code == 200
