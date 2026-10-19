# botsim

Simulated robots for one site, from two fictional vendors. Field names, units and transports differ on purpose so the site gateway has real normalization work to do. Wire formats are [below](#wire-formats).

Compose runs the same image twice per site. For site 1 these are the following.

- `site1-bot-rovo` is one container with `ROVO_COUNT` robots. Each robot is a goroutine with its own MQTT connection that pushes telemetry.
- `site1-bot-cleanix` is one container per robot, so each robot has its own IP and HTTP server on port 8080 that has to be polled. Resolving the service name `site1-bot-cleanix` returns every robot's IP, which is how the site gateway discovers them here.

## Run

From the repo root.

```bash
ROVO_COUNT=5 CLEANIX_COUNT=5 docker compose up -d --build
```

Here the counts are robots per type for site 1, 5 of each by default. Site 2 is fixed at 3 Rovo and 2 Cleanix in compose. Compose turns `CLEANIX_COUNT` into that many containers, up to the 50 host ports it publishes. To change the fleet size, change the counts and run the same command again. Serials come from the container name, like `olivaw-site1-bot-cleanix-3`, so robots keep their serial when containers are recreated.

## Config

Env of one botsim process. Compose sets the counts and passes the rest through.

| Env | Default | |
|---|---|---|
| `ROVO_COUNT` | 0 | Rovo robots in this process |
| `CLEANIX_COUNT` | 0 | Cleanix robot in this process, 0 or 1 |
| `MQTT_URL` | `tcp://localhost:1883` | Broker for Rovo |
| `CLEANIX_ADDR` | `:8080` | Where the Cleanix robot listens |
| `SIM_ID` | container name | Namespaces serials so two simulators do not collide |
| `TICK` | `1s` | Reading interval |
| `MAP_WIDTH_M`, `MAP_HEIGHT_M` | 40, 25 | Map size in meters |
| `CHAOS_ERROR_RATE` | 0.002 | Chance per robot per tick |
| `CHAOS_STUCK_RATE` | 0.001 | Reports working but stops moving |
| `CHAOS_DROPOUT_RATE` | 0.0005 | Goes silent for 15 to 90s |
| `CHAOS_DELAY_RATE` | 0.03 | Sends a reading 1 to 4s late |
| `SEED` | random, logged at start | Fix it to replay the same serials and chaos sequence. Paths still follow wall clock time. |

## Check it

```bash
docker compose exec site1-mosquitto mosquitto_sub -t 'rovo/+/telemetry' -v
```

Cleanix containers get a free host port from 9101 to 9150, for curl only. This asks robot 1 for its status.

```bash
curl -s "$(docker compose port --index 1 site1-bot-cleanix 8080)/api/v1/status"
```

## Wire formats

Robots report only what a robot knows. No site, no floor and serials like `rv-3f9a21` carry no location. Positions are in the robot's own map frame.

| | Rovo | Cleanix |
|---|---|---|
| Transport | Pushes to the site MQTT broker | Own HTTP server, must be polled |
| Battery | `battery` integer 0..100 | `battery_level` float 0.0..1.0 |
| Position | meters | centimeters |
| Time | `timestamp` epoch ms, plus per-robot `seq` | `ts` RFC 3339, no `seq` |
| Errors | `errorCode` 101 wheel stuck, 102 bumper hit, 103 localization lost, 0 none | `fault.code` E201 wheel stuck, E102 bumper hit, E310 localization lost, or `null` |
| States | `IDLE` `WORKING` `RETURNING` `CHARGING` `PAUSED` `ERROR` | `idle` `cleaning` `returning_home` `docked_charging` `paused` `fault` |
| Commands | `PAUSE` `RESUME` `DOCK` `GOTO` (`params.x`, `params.y` in m) | `pause` `resume` `go_home` `navigate` (`target.x_cm`, `target.y_cm`) |

### Rovo over MQTT

Each robot holds its own connection with the serial as client id.

| Topic | Direction | Payload |
|---|---|---|
| `rovo/{serial}/telemetry` | robot to broker, 1 Hz | `{"robotId", "model", "timestamp", "seq", "battery", "status", "errorCode", "pose": {"x", "y", "theta"}, "speed"}` |
| `rovo/{serial}/online` | robot to broker, retained | `1` on connect, `0` as last will or on shutdown |
| `rovo/{serial}/cmd` | to robot | `{"cmdId", "action", "params"}` |
| `rovo/{serial}/cmd/ack` | robot to broker | `{"cmdId", "result": "OK" or "REJECTED", "reason", "timestamp"}`. No ack while the robot is offline. |

### Cleanix over HTTP

Every robot serves `http://{robot-ip}:8080/api/v1`.

| Request | Response |
|---|---|
| `GET /info` | `{"serial", "model"}`. Used for discovery. |
| `GET /status` | `{"serial", "model", "ts", "battery_level", "work_state", "fault", "location": {"x_cm", "y_cm", "heading_deg"}}`, or `503` while unreachable |
| `POST /commands` with `{"command", "target"}` | `202 {"task_id", "accepted"}`, `409 {"error"}` if the robot refuses, `503` while unreachable |

## Test

```bash
make test-botsim
```
