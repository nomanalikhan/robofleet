"""Central ingest. Consumes gateway batches and stores them. Run with python main.py.

Acks only after commit, so a crash means redelivery and never loss. A batch
that cannot be parsed, or whose data the database refuses, is rejected to the
dead-letter queue so it cannot block the queue. Any other error, including a
dropped broker connection, exits the process and Docker restarts it.
"""

import asyncio
import logging
import os
import zlib

import aio_pika
import asyncpg

from batch import parse
from store import connect, save

QUEUE = "central.telemetry"
log = logging.getLogger("ingest")


async def handle(con: asyncpg.Connection, message: aio_pika.abc.AbstractIncomingMessage) -> None:
    try:
        batch = parse(message.body)
    except (OSError, EOFError, ValueError, zlib.error) as e:
        log.error("dead-lettering unreadable batch: %s", e)
        await message.reject(requeue=False)
        return
    try:
        new = await save(con, batch)
    except (asyncpg.DataError, asyncpg.IntegrityConstraintViolationError) as e:
        log.error("dead-lettering unstorable batch from %s: %s", batch.site_id, e)
        await message.reject(requeue=False)
        return
    await message.ack()
    log.info(
        "%s: %d readings, %d new, %d still waiting on site",
        batch.site_id, len(batch.readings), new, batch.backlog.readings,
    )


async def main() -> None:
    con = await connect(os.environ["DATABASE_URL"])
    amqp = await aio_pika.connect(os.environ["AMQP_URL"])
    # The queue iterator only waits for the next message, so without this a
    # dropped broker connection leaves the process alive and consuming nothing.
    task = asyncio.current_task()
    amqp.close_callbacks.add(lambda _, exc: task.cancel(f"amqp connection closed: {exc!r}"))
    channel = await amqp.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.get_queue(QUEUE)
    log.info("consuming %s", QUEUE)

    async with queue.iterator() as messages:
        async for message in messages:
            await handle(con, message)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
