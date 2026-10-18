# central ingest

Consumes gateway batches from the RabbitMQ queue `central.telemetry` and stores them in TimescaleDB. It stores facts only. Health, like offline, stuck or low battery, is computed by the Fleet API when asked.

Each batch is one transaction that upserts the site and its robots and inserts the readings, skipping any `(robot_id, ts)` already stored, so a batch sent twice adds nothing. Only a newer batch moves a site's heartbeat and backlog, so a late or redelivered one cannot move them backwards.

The message is acked only after the commit, so a crash means redelivery and never loss. A batch that fails validation goes to `central.telemetry.dead` for inspection instead of blocking the queue. Any other error exits the process and Docker restarts it.

## Schema

[schema.sql](schema.sql), applied at startup. Tables `sites`, `robots` and the hypertable `robot_telemetry` with daily chunks and 30 day retention. There is no current state table. The newest reading per robot is a query.

```sql
SELECT DISTINCT ON (robot_id) *
FROM robot_telemetry
WHERE ts > now() - INTERVAL '1 hour'
ORDER BY robot_id, ts DESC;
```

## Run

From the repo root.

```bash
docker compose up -d --build
```

Open psql on the fleet database.

```bash
make central-db
```

Needs `AMQP_URL` and `DATABASE_URL`, both set by compose.

## Test

```bash
make test-ingest
```
