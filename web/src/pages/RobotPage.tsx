import { LineChart } from '@mantine/charts'
import {
  Alert, Anchor, Badge, Group, Paper, RingProgress, SegmentedControl, SimpleGrid, Stack, Text, Title, Tooltip,
} from '@mantine/core'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useGetRobot, useGetTelemetry, type GetActivityPeriod, type TelemetryPoint, type TelemetryPointState } from '../api/fleet'
import { Legend, Stat, StatusBadge, Trail, Updated } from '../ui'
import { LIVE, PERIODS, STATE_COLORS, batteryColor, bucketLabel, chartRefetch, cssColor, label, seconds, timeAxis } from '../theme'

export default function RobotPage() {
  const { robotId = '' } = useParams()
  const [period, setPeriod] = useState<GetActivityPeriod>('hour')
  const robot = useGetRobot(robotId, { query: LIVE })
  // Charts change slowly, so they refresh far less often than the live details.
  const telemetry = useGetTelemetry(robotId, { period }, { query: { refetchInterval: chartRefetch } })

  if (robot.isError) return <Alert color="red" title="Robot not found">No robot called {robotId}.</Alert>
  if (!robot.data) return <Text c="dimmed">Loading…</Text>

  const r = robot.data
  const points = telemetry.data?.points ?? []
  const battery = points.map((p) => ({ t: dayjs(p.ts).valueOf(), battery: Math.round(p.battery_pct), state: p.state, error: p.error }))
  // One line where each error starts, not one per reading while it lasts.
  const errorStarts = battery.filter((d, i) => d.error && d.error !== battery[i - 1]?.error)
  const bucket = telemetry.data?.bucket_s
  const { from, to, xAxisProps } = timeAxis(period, telemetry.dataUpdatedAt || Date.now())

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Group gap="sm">
            <Title order={2}>{r.id}</Title>
            <StatusBadge status={r.status} />
            {r.problems.filter((p) => p !== r.status).map((p) => <Badge key={p} variant="outline" color="gray">{label(p)}</Badge>)}
          </Group>
          <Text size="sm" c="dimmed">
            {r.vendor} at <Anchor component={Link} to={`/sites/${r.site_id}`} size="sm">{r.site_id}</Anchor> · last seen {seconds(r.last_seen_s)}
          </Text>
        </div>
        <Updated at={robot.dataUpdatedAt} />
      </Group>

      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Paper withBorder p="md">
          <Group>
            <RingProgress size={72} thickness={8} roundCaps
              sections={[{ value: r.battery_pct ?? 0, color: batteryColor(r.problems) }]}
              label={<Text ta="center" size="sm" fw={700}>{r.battery_pct == null ? '–' : `${Math.round(r.battery_pct)}%`}</Text>} />
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Battery</Text>
          </Group>
        </Paper>
        <Stat title="State" value={<Text inherit c={r.state ? cssColor(STATE_COLORS[r.state]) : undefined}>{r.state ?? '–'}</Text>} />
        <Stat title="Error" value={<Text inherit c={r.error ? 'red.4' : 'dimmed'}>{r.error ? label(r.error) : 'none'}</Text>} />
        <Stat title="Position" value={r.x_m == null ? '–' : `${r.x_m.toFixed(1)}, ${r.y_m!.toFixed(1)} m`} />
      </SimpleGrid>

      <Paper withBorder p="md">
        <Group justify="space-between" mb="sm">
          <div>
            <Text fw={600}>Telemetry</Text>
            <Text size="xs" c="dimmed">{bucket ? `each point averages ${bucketLabel(bucket)}` : 'raw readings, one per second'}</Text>
          </div>
          <SegmentedControl size="xs" value={period} onChange={(v) => setPeriod(v as GetActivityPeriod)} data={PERIODS} />
        </Group>
        {points.length ? (
          <Stack gap="md">
            <Text size="sm" fw={600}>Battery</Text>
            <LineChart h={220} data={battery} dataKey="t" series={[{ name: 'battery', color: 'teal.5' }]}
              withDots={false} yAxisProps={{ domain: [0, 100] }} unit="%" curveType="monotone"
              xAxisProps={xAxisProps}
              referenceLines={errorStarts.map((d) => ({ x: d.t, color: 'red.6', strokeDasharray: '4 3' }))}
              tooltipProps={{ content: ({ payload }) => <BatteryTooltip point={payload?.[0]?.payload} bucket={bucket} /> }} />
            {errorStarts.length > 0 && (
              <Text size="xs" c="dimmed">
                <Text span c="red.5" fw={700}>¦</Text> {errorStarts.length} error{errorStarts.length > 1 ? 's' : ''} in this period, hover the chart for details
              </Text>
            )}
            <Group justify="space-between">
              <Text size="sm" fw={600}>State over time</Text>
              <Legend colors={STATE_COLORS} />
            </Group>
            <StateTimeline points={points} from={from} to={to} />
          </Stack>
        ) : (
          <Text c="dimmed" size="sm">{telemetry.isLoading ? 'Loading…' : 'No readings in this period.'}</Text>
        )}
      </Paper>

      {/* Only raw readings make a real path, and ten minutes of it stays readable. */}
      {period === 'hour' && points.length > 1 && (
        <Paper withBorder p="md">
          <Text fw={600} mb="sm">Where it drove, last 10 minutes</Text>
          <Trail points={points.slice(-600)} />
        </Paper>
      )}
    </Stack>
  )
}

type BatteryPoint = { t: number; battery: number; state: TelemetryPointState; error?: string | null }

function BatteryTooltip({ point, bucket }: { point?: BatteryPoint; bucket?: number | null }) {
  if (!point) return null
  return (
    <Paper withBorder shadow="md" p="xs" miw={170}>
      <Text size="xs" c="dimmed">{dayjs(point.t).format(bucket ? 'MMM D HH:mm' : 'HH:mm:ss')}</Text>
      <Text size="sm">battery <b>{point.battery}%</b>{bucket ? ' average' : ''}</Text>
      <Text size="sm">state <b style={{ color: cssColor(STATE_COLORS[point.state]) }}>{point.state}</b></Text>
      {point.error && <Text size="sm" c="red.4" fw={700}>error: {label(point.error)}</Text>}
    </Paper>
  )
}

/** One colored band per stretch of time the robot spent in a state. */
function StateTimeline({ points, from, to }: { points: TelemetryPoint[]; from: number; to: number }) {
  const span = to - from
  const stretches: { state: TelemetryPointState; from: number; to: number }[] = []
  for (const p of points) {
    const t = dayjs(p.ts).valueOf()
    const last = stretches[stretches.length - 1]
    if (last && last.state === p.state) last.to = t
    else {
      if (last) last.to = t
      stretches.push({ state: p.state, from: t, to: t })
    }
  }
  return (
    <div style={{ position: 'relative', height: 28, borderRadius: 6, overflow: 'hidden', background: 'var(--mantine-color-dark-6)' }}>
      {stretches.map((s) => (
        <Tooltip key={s.from} label={`${s.state}, ${dayjs(s.from).format('HH:mm')} to ${dayjs(s.to).format('HH:mm')}`}>
          <div style={{
            position: 'absolute', top: 0, bottom: 0,
            left: `${Math.max(0, ((s.from - from) / span) * 100)}%`,
            width: `${Math.max(0.3, ((s.to - s.from) / span) * 100)}%`,
            background: cssColor(STATE_COLORS[s.state]),
          }} />
        </Tooltip>
      ))}
    </div>
  )
}
