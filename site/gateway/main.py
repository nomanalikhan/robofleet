"""Site gateway entry point. Run with python main.py."""

import asyncio
import logging
import signal

from config import Config
from store import Store
from vendors import cleanix, rovo

log = logging.getLogger("gateway")


async def flusher(store: Store, cfg: Config) -> None:
    """Write buffered readings once a second and prune history once a minute."""
    tick = 0
    while True:
        await asyncio.sleep(1)
        store.flush()
        tick += 1
        if tick % 60 == 0 and (pruned := store.prune(cfg.uploaded_keep_s, cfg.retention_hours)):
            log.info("pruned %d old readings", pruned)


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
    ]
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    await stop.wait()

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("shutting down, flushed %d readings", store.flush())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per poll otherwise
    asyncio.run(main())
