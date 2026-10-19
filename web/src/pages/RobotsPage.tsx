import { Anchor, Group, MultiSelect, Pagination, Paper, Progress, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconSearch } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { useListRobots, useListSites, type ListRobotsParams, type RobotStatus } from '../api/fleet'
import { StatusBadge, Updated } from '../ui'
import { LIVE, STATUSES, batteryColor, label, seconds } from '../theme'

const PAGE_SIZE = 25

export default function RobotsPage() {
  const navigate = useNavigate()
  // Filters live in the URL, so a filtered view can be shared or bookmarked.
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const [q] = useDebouncedValue(search, 300)
  const page = Number(params.get('page') ?? 1)

  // Each filter is a repeated param, ?status=error&status=stuck, the same shape the API takes.
  const set = (key: string, values: string[]) => {
    const next = new URLSearchParams(params)
    next.delete(key)
    values.forEach((v) => next.append(key, v))
    if (key !== 'page') next.delete('page')
    setParams(next, { replace: true })
  }

  const filters: ListRobotsParams = {
    site_id: params.getAll('site_id'),
    status: params.getAll('status') as RobotStatus[],
    vendor: params.getAll('vendor'),
    q: q || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  }
  const sites = useListSites()
  const robots = useListRobots(filters, { query: { ...LIVE, placeholderData: (prev) => prev } })
  const vendors = [...new Set(sites.data?.flatMap((s) => Object.keys(s.robots_by_vendor)))]
  const items = robots.data?.items ?? []
  const total = robots.data?.total ?? 0

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Robots</Title>
          <Text size="sm" c="dimmed">{total} robots, worst problems first</Text>
        </div>
        <Updated at={robots.dataUpdatedAt} />
      </Group>

      <Group>
        <TextInput
          placeholder="Search robot id"
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => {
            setSearch(e.currentTarget.value)
            set('page', [])
          }}
          w={220}
        />
        <MultiSelect placeholder={filters.site_id?.length ? undefined : 'All sites'} clearable miw={160} value={filters.site_id}
          data={sites.data?.map((s) => s.id) ?? []} onChange={(v) => set('site_id', v)} />
        <MultiSelect placeholder={filters.status?.length ? undefined : 'Any status'} clearable miw={160} value={filters.status}
          data={STATUSES.map((s) => ({ value: s, label: label(s) }))} onChange={(v) => set('status', v)} />
        <MultiSelect placeholder={filters.vendor?.length ? undefined : 'Any vendor'} clearable miw={160} value={filters.vendor}
          data={vendors} onChange={(v) => set('vendor', v)} />
      </Group>

      <Paper withBorder>
        <Table highlightOnHover verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Robot</Table.Th>
              <Table.Th>Site</Table.Th>
              <Table.Th>Vendor</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>State</Table.Th>
              <Table.Th>Error</Table.Th>
              <Table.Th w={160}>Battery</Table.Th>
              <Table.Th>Last seen</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((r) => (
              <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/robots/${r.id}`)}>
                <Table.Td><Anchor component={Link} to={`/robots/${r.id}`} fw={600}>{r.id}</Anchor></Table.Td>
                <Table.Td>{r.site_id}</Table.Td>
                <Table.Td>{r.vendor}</Table.Td>
                <Table.Td><StatusBadge status={r.status} /></Table.Td>
                <Table.Td>{r.state ?? '–'}</Table.Td>
                <Table.Td><Text size="sm" c={r.error ? 'red.4' : 'dimmed'}>{r.error ? label(r.error) : '–'}</Text></Table.Td>
                <Table.Td>
                  {r.battery_pct == null ? '–' : (
                    <Group gap="xs" wrap="nowrap">
                      <Progress value={r.battery_pct} w={90} color={batteryColor(r.problems)} />
                      <Text size="sm">{Math.round(r.battery_pct)}%</Text>
                    </Group>
                  )}
                </Table.Td>
                <Table.Td><Text size="sm" c="dimmed">{seconds(r.last_seen_s)}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {!items.length && <Text c="dimmed" p="lg" ta="center">{robots.isLoading ? 'Loading…' : 'No robots match these filters.'}</Text>}
      </Paper>

      {total > PAGE_SIZE && (
        <Pagination value={page} total={Math.ceil(total / PAGE_SIZE)} onChange={(p) => set('page', [String(p)])} />
      )}
    </Stack>
  )
}
