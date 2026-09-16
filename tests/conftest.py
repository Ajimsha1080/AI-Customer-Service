import pytest
import pytest_asyncio
from apps.api.main import init_db_and_seed

@pytest_asyncio.fixture(autouse=True, scope="function")
async def prepare_db():
    """Ensure DB schema and initial seed data exist before running tests."""
    await init_db_and_seed()
