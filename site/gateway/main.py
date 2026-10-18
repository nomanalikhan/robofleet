"""Site gateway entry point. Run with python main.py."""

import asyncio
import logging
import signal

from config import Config
from store import Store
from uplink import run as uplink
from vendors import cleanix, rovo

log = logging.getLogger("gateway")


async def flusher(store: Store, cfg: Config) -> None:
    """Write buffered readings once a second. Once a minute, enforce the cap on
    undelivered readings, which only bites when the uplink is down for a day."""
    tick = 0
    while True:
        await asyncio.sleep(1)
        store.flush()
        tick += 1
        if tick % 60 == 0 and (dropped := store.prune(cfg.retention_hours)):
            log.warning("dropped %d undelivered readings older than %gh", dropped, cfg.retention_hours)


async def main() -> None:
    cfg = Config.from_env()
    store = Store(cfg.db_path)
    log.info("site gateway for %s, db %s", cfg.site_id, cfg.db_path)

    tasks = [
        asyncio.create_task(flusher(store, cfg)),
        asyncio.create_task(rovo.run(store, cfg.mqtt_host, cfg.mqtt_port, f"gateway-{cfg.site_id}")),
        asyncio.create_task(
            cleanix.run(store, cfg.cleanix_discovery, cfg.discovery_interval_s, cfg.poll_interval_s)
        ),
        asyncio.create_task(uplink(store, cfg.amqp_url, cfg.site_id, cfg.uplink_interval_s, cfg.batch_limit)),
    ]
    stop = asyncio.create_task(asyncio.Event().wait())
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.cancel)

    # Every task runs forever, so one that returns has died. Exit instead of
    # running without it, and let Docker restart the gateway.
    done, _ = await asyncio.wait([stop, *tasks], return_when=asyncio.FIRST_COMPLETED)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("shutting down, flushed %d readings", store.flush())
    if crashed := [t for t in done if t is not stop]:
        log.error("a task died", exc_info=crashed[0].exception())
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per poll otherwise
    asyncio.run(main())
