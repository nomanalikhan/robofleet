# web

The fleet manager's UI. React, Vite and TypeScript with Mantine in a dark theme, TanStack Query for data and Orval for a client generated from the Fleet API spec.

| Page | Shows |
|---|---|
| `/sites/:siteId` | Status and heartbeat, robot and health counts, robots by vendor, what the fleet was doing over the last hour, day, week or month, a live floor map and the robots that need attention |
| `/robots` | Every robot worst first, filtered by site, status, vendor or id. Filters live in the URL so a view can be shared. |
| `/robots/:robotId` | Live details, battery and a state timeline for the last hour, day, week or month, and the last 10 minutes of its path |

Live views refetch every 5s and show how long ago they updated, so a stalled feed is visible. Charts refetch every minute.

## Run

With the stack up, the UI is on http://localhost:3000. nginx serves the build and forwards `/api` to the Fleet API.

For development with hot reload, against the running API.

```bash
npm install
```

```bash
npm run dev
```

## API client

[src/api/fleet.ts](src/api/fleet.ts) is generated, do not edit it. After an API change, regenerate it while the API runs.

```bash
make web-api
```
