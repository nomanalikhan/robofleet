"""Ships telemetry to central every few seconds and deletes it once delivered.

Every interval the gateway sends one batch with every reading central has not
confirmed yet, even an empty one, so the batch doubles as the site heartbeat.
RabbitMQ publisher confirms decide what was delivered. A confirmed batch is
deleted from SQLite. A failed one stays and goes out with the next batch.

The gateway only ever dials out, because sites sit behind customer firewalls.
"""

import asyncio
import gzip
import json
import logging
from collections.abc import Awaitable, Callable

import aio_pika

from store import Store, now_ms

EXCHANGE = "fleet"
log = logging.getLogger(__name__)

Publish = Callable[[bytes], Awaitable[None]]


def build_batch(store: Store, site_id: str, limit: int) -> tuple[bytes, list[tuple[str, int]]]:
    """The next batch as gzipped JSON, plus the keys of the readings in it."""
    readings = store.unsent(limit)
    pending, oldest_ms = store.backlog()
    body = {
        "site_id": site_id,
        "sent_ms": now_ms(),
        "backlog": {"readings": pending, "oldest_received_ms": oldest_ms},
        "robots": store.robots(),
        "readings": readings,
    }
    keys = [(r["robot_id"], r["ts_ms"]) for r in readings]
    return gzip.compress(json.dumps(body, separators=(",", ":")).encode()), keys


async def send_once(store: Store, publish: Publish, site_id: str, limit: int) -> int:
    """Send one batch and delete what was delivered. Raises if delivery failed,
    in which case nothing is deleted. Returns how many readings went out."""
    body, keys = build_batch(store, site_id, limit)
    await publish(body)
    store.delivered(keys)
    return len(keys)


def publisher(exchange: aio_pika.abc.AbstractExchange, routing_key: str) -> Publish:
    async def publish(body: bytes) -> None:
        message = aio_pika.Message(
            body,
            content_type="application/json",
            content_encoding="gzip",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key, mandatory=True, timeout=10)

    return publish


async def run(store: Store, amqp_url: str, site_id: str, interval_s: float, batch_limit: int) -> None:
    """Keep a connection to central and send a batch every interval, forever."""
    routing_key = f"site.{site_id}.telemetry"
    while True:
        try:
            async with await aio_pika.connect(amqp_url, timeout=10) as conn:
                # Confirms tell us RabbitMQ stored the batch. on_return_raises
                # turns "no queue bound for this routing key" into an error too.
                channel = await conn.channel(publisher_confirms=True, on_return_raises=True)
                exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
                publish = publisher(exchange, routing_key)
                log.info("uplink: connected, sending to %s every %gs", routing_key, interval_s)
                while True:
                    sent = await send_once(store, publish, site_id, batch_limit)
                    if sent < batch_limit:  # a full batch means a backlog, keep draining
                        await asyncio.sleep(interval_s)
        except Exception as e:  # noqa: BLE001  any failure here means reconnect and resend
            # Safe to retry blindly. Readings are only deleted after a confirm,
            # and central drops duplicates.
            pending, _ = store.backlog()
            log.warning("uplink: %s: %s, %d readings waiting, retrying in 5s", type(e).__name__, e, pending)
            await asyncio.sleep(5)
