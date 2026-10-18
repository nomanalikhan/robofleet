"""Central ingest. Consumes gateway batches and stores them. Run with python main.py.

Acks only after commit, so a crash means redelivery and never loss. A batch
that cannot be parsed is rejected to the dead-letter queue so it cannot block
the queue. Any other error exits the process and Docker restarts it.
"""

import asyncio
import logging
import os

import aio_pika

from batch import parse
from store import connect, save

QUEUE = "central.telemetry"
log = logging.getLogger("ingest")


async def main() -> None:
    con = await connect(os.environ["DATABASE_URL"])
    amqp = await aio_pika.connect(os.environ["AMQP_URL"])
    channel = await amqp.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.get_queue(QUEUE)
    log.info("consuming %s", QUEUE)

    async with queue.iterator() as messages:
        async for message in messages:
            try:
                batch = parse(message.body)
            except (OSError, EOFError, ValueError) as e:
                log.error("dead-lettering unreadable batch: %s", e)
                await message.reject(requeue=False)
                continue
            new = await save(con, batch)
            await message.ack()
            log.info(
                "%s: %d readings, %d new, %d still waiting on site",
                batch.site_id, len(batch.readings), new, batch.backlog.readings,
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
