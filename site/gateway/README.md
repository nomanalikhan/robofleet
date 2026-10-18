# site gateway

Runs on each site and is the only link between the site's robots and central. Central never talks to a robot directly.

- **Up.** Finds every robot on the local network whatever its vendor, translates each vendor's format into one canonical reading, keeps the history in SQLite and forwards it to central.
- **Down.** Takes commands from central, routes each to the right robot through its vendor adapter and reports the outcome back.

Built so far is discovery, normalization and local storage. Forwarding to central and executing commands come next.

Every vendor is one adapter in `vendors/`. An adapter knows how to discover that vendor's robots, how to get their data, how to map fields, units and enums and how to send them commands. Two adapters exist today. Their wire formats are in the [botsim README](../../simulator/botsim/README.md#wire-formats).

| Adapter | How the gateway gets data |
|---|---|
| Rovo | Subscribes to `rovo/+/telemetry` and `rovo/+/online` on the site broker. A new serial is a new robot. |
| Cleanix | Resolves `CLEANIX_DISCOVERY` every 30s (5s after a miss), probes `/api/v1/info` on each IP and polls `/api/v1/status` once a second. A robot that moves to a new IP keeps its serial and its stored IP is updated. |

Resolving a name to find Cleanix robots is a simulation stand-in. Docker DNS returns every replica of the compose service. A real site has no such name, so candidates would come from a subnet scan of the robot network or a static list of addresses. Only `resolve()` in `vendors/cleanix.py` would change, because probing and polling stay the same.

Storage is two tables, `robots` and `robot_telemetry`, plus a `latest` view that returns each robot's newest reading by robot time. A late reading goes into history but never becomes latest. Pruning never removes a robot's newest reading.

To add a vendor, write a module in `vendors/` with a `normalize()` that returns a `Reading` and a `run()` that discovers robots and feeds the store, then start it in `main.py`.

## Run

From the repo root.

```bash
docker compose up -d --build
```

## See what it stored

`show_state.py` prints every robot the gateway knows with its newest reading, straight from SQLite. Run it inside the gateway container.

```bash
make gateway-state
```

That is the same as the following command.

```bash
docker compose exec site1-gateway python show_state.py
```

```
robot       vendor   state      error               batt       x,y (m)    age   rows
cx-260723   cleanix  working                        48.7   12.5,  19.2   1.0s    719
rv-14fa03   rovo     charging                       41.0    1.0,   1.0   0.9s    702
```

`age` is how long ago the newest reading was measured. Around 1s means data is flowing, a growing age means the robot went quiet. `rows` is how many readings of that robot are stored.

## Config

| Env | Default | |
|---|---|---|
| `SITE_ID` | required | Which site this gateway serves |
| `DB_PATH` | `/data/gateway.db` | SQLite file |
| `MQTT_HOST`, `MQTT_PORT` | required, 1883 | Site broker |
| `CLEANIX_DISCOVERY` | required | Name and port that resolve to Cleanix robots |
| `DISCOVERY_INTERVAL_S` | 30 | How often to look for new or gone Cleanix robots |
| `POLL_INTERVAL_S` | 1 | Cleanix status polling |
| `UPLOADED_KEEP_S` | 600 | How long history stays after central confirmed it |
| `RETENTION_HOURS` | 24 | Hard cap for history that never got uploaded, so a dead uplink cannot fill the disk |

## Test

```bash
make test-gateway
```
