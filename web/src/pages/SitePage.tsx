import { AreaChart, BarChart, ChartTooltip, DonutChart, LineChart, type ChartTooltipProps } from '@mantine/charts'
import { Alert, Anchor, Group, Paper, SegmentedControl, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useGetActivity, useGetSite, useListRobots, type GetActivityPeriod } from '../api/fleet'
import { FloorMap, Legend, SiteBadge, Stat, StatusBadge, Updated } from '../ui'
import { LIVE, PERIODS, STATE_COLORS, STATES, STATUS_COLORS, STATUSES, bucketLabel, chartRefetch, label, seconds, timeAxis } from '../theme'

const VENDOR_COLORS = ['blue.6', 'violet.6', 'cyan.6', 'grape.6']

export default function SitePage() {
  const { siteId = '' } = useParams()
  const [period, setPeriod] = useState<GetActivityPeriod>('hour')
  const site = useGetSite(siteId, { query: LIVE })
  const robots = useListRobots({ site_id: [siteId], limit: 500 }, { query: LIVE })
  const activity = useGetActivity(siteId, { period }, { query: { refetchInterval: chartRefetch } })

  if (site.isError) return <Alert color="red" title="Site not found">No site called {siteId}.</Alert>
  if (!site.data || !robots.data) return <Text c="dimmed">Loading…</Text>

  const s = site.data
  const items = robots.data.items
  const total = Object.values(s.robots_by_status).reduce((a, n) => a + n, 0)
  const healthy = s.robots_by_status.ok ?? 0
  const charged = items.filter((r) => r.battery_pct != null)
  const avgBattery = charged.length ? charged.reduce((a, r) => a + r.battery_pct!, 0) / charged.length : null
  const vendors = Object.entries(s.robots_by_vendor).map(([name, value], i) => ({
    name, value, color: VENDOR_COLORS[i % VENDOR_COLORS.length],
  }))
  const health = STATUSES.map((st) => ({ status: label(st), robots: s.robots_by_status[st] ?? 0, color: STATUS_COLORS[st] }))
  const attention = items.filter((r) => r.status !== 'ok')
  const points = (activity.data?.points ?? []).map((p) => ({ ...p, t: dayjs(p.ts).valueOf(), battery: Math.round(p.battery_pct) }))
  const { xAxisProps } = timeAxis(period, activity.dataUpdatedAt || Date.now())
  const stateSeries = STATES.map((st) => ({ name: st, color: STATE_COLORS[st] }))
  const batterySeries = [{ name: 'battery', color: 'yellow.5' }]

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Group gap="sm">
            <Title order={2}>{s.id}</Title>
            <SiteBadge status={s.status} size="lg" variant="light" />
          </Group>
          <Text size="sm" c="dimmed">
            last batch {dayjs(s.last_sent_at).fromNow()} · {s.backlog_readings} readings waiting on site
          </Text>
        </div>
        <Updated at={site.dataUpdatedAt} />
      </Group>

      {s.status === 'offline' && (
        <Alert color="red" icon={<IconAlertTriangle />} title="Site offline">
          No batch from this site since {dayjs(s.last_sent_at).format('HH:mm:ss')}. Its robots show as unknown until it reports again.
        </Alert>
      )}

      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Stat title="Robots" value={total} hint={vendors.map((v) => `${v.value} ${v.name}`).join(' · ')} />
        <Stat title="Healthy" value={healthy} hint={`${total ? Math.round((healthy / total) * 100) : 0}% of the site`} />
        <Stat title="Need attention" value={<Text inherit c={attention.length ? 'red.5' : undefined}>{attention.length}</Text>} hint="error, stuck, low battery, offline, unknown" />
        <Stat title="Average battery" value={avgBattery == null ? '–' : `${Math.round(avgBattery)}%`} hint="across reporting robots" />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Paper withBorder p="md">
          <Text fw={600} mb="sm">Robots by vendor</Text>
          <Group justify="center">
            <DonutChart data={vendors} withLabelsLine withLabels chartLabel={`${total} robots`} size={180} thickness={26} />
          </Group>
        </Paper>
        <Paper withBorder p="md">
          <Text fw={600} mb="sm">Health right now</Text>
          <BarChart h={200} data={health} dataKey="status" series={[{ name: 'robots', color: 'teal.6' }]} withTooltip={false} />
        </Paper>
      </SimpleGrid>

      <Paper withBorder p="md">
        <Group justify="space-between" mb="sm">
          <div>
            <Text fw={600}>What the fleet was doing</Text>
            <Text size="xs" c="dimmed">robots per state, each robot counted once per {activity.data ? bucketLabel(activity.data.bucket_s) : '…'}</Text>
          </div>
          <SegmentedControl size="xs" value={period} onChange={(v) => setPeriod(v as GetActivityPeriod)} data={PERIODS} />
        </Group>
        {points.length ? (
          <Stack gap="xs">
            <AreaChart h={240} data={points} dataKey="t" type="stacked" curveType="step" withDots={false}
              series={stateSeries} xAxisProps={xAxisProps} tooltipProps={timeTooltip(stateSeries)} />
            <Legend colors={STATE_COLORS} />
            <Text size="sm" fw={600} mt="sm">Average battery</Text>
            <LineChart h={120} data={points} dataKey="t" series={batterySeries} withDots={false}
              yAxisProps={{ domain: [0, 100] }} unit="%" xAxisProps={xAxisProps} tooltipProps={timeTooltip(batterySeries, '%')} />
          </Stack>
        ) : (
          <Text c="dimmed" size="sm">No readings in this period yet.</Text>
        )}
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Paper withBorder p="md">
          <Group justify="space-between" mb="sm">
            <Text fw={600}>Floor map, right now</Text>
            <Legend colors={Object.fromEntries(Object.entries(STATUS_COLORS).filter(([k]) => k !== 'unknown'))} />
          </Group>
          <FloorMap robots={items} />
          <Text size="xs" c="dimmed" mt="xs">positions in each robot's own map frame, metres</Text>
        </Paper>
        <Paper withBorder p="md">
          <Text fw={600} mb="sm">Needs attention</Text>
          {attention.length ? (
            <Table verticalSpacing="xs">
              <Table.Tbody>
                {attention.map((r) => (
                  <Table.Tr key={r.id}>
                    <Table.Td><Anchor component={Link} to={`/robots/${r.id}`}>{r.id}</Anchor></Table.Td>
                    <Table.Td><StatusBadge status={r.status} /></Table.Td>
                    <Table.Td><Text size="sm" c="dimmed">{r.error ? label(r.error) : r.battery_pct != null ? `${Math.round(r.battery_pct)}%` : ''}</Text></Table.Td>
                    <Table.Td><Text size="sm" c="dimmed">{seconds(r.last_seen_s)}</Text></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          ) : (
            <Text c="teal" size="sm">Every robot is healthy.</Text>
          )}
          <Anchor component={Link} to={`/robots?site_id=${s.id}`} size="sm" mt="md" display="block">All robots at {s.id} →</Anchor>
        </Paper>
      </SimpleGrid>
    </Stack>
  )
}

/** Mantine's chart tooltip, with the numeric time key shown as a time. */
function timeTooltip(series: ChartTooltipProps['series'], unit?: string) {
  return {
    content: ({ label, payload }: { label?: number; payload?: ChartTooltipProps['payload'] }) => (
      <ChartTooltip label={dayjs(label).format('MMM D HH:mm')} payload={payload ?? []} series={series} unit={unit} />
    ),
  }
}
