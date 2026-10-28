import os

import pytest

from zapagent.config import Settings

requires_infra = pytest.mark.skipif(
    "ZAPAGENT_INTEGRATION" not in os.environ, reason="ZAPAGENT_INTEGRATION não definido"
)


@pytest.fixture
def settings() -> Settings:
    return Settings(mongo_db="zapagent_test")
