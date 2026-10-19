import asyncio

import asyncpg
import pytest
from test_batch import batch

import main


class Message:
    body = batch()
    outcome = None

    async def ack(self):
        self.outcome = "ack"

    async def reject(self, requeue):
        self.outcome = ("reject", requeue)


def failing_save(error):
    async def save(con, batch):
        raise error
    return save


def test_data_the_database_refuses_is_dead_lettered(monkeypatch):
    monkeypatch.setattr(main, "save", failing_save(asyncpg.DataError("value out of range")))
    message = Message()
    asyncio.run(main.handle(None, message))
    assert message.outcome == ("reject", False)


def test_other_save_failures_still_crash(monkeypatch):
    monkeypatch.setattr(main, "save", failing_save(asyncpg.PostgresConnectionError()))
    message = Message()
    with pytest.raises(asyncpg.PostgresConnectionError):
        asyncio.run(main.handle(None, message))
    assert message.outcome is None
