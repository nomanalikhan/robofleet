import { Badge, Group, Paper, Text, Tooltip, type BadgeProps } from '@mantine/core'
import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import type { Robot, RobotStatus, SiteStatus } from './api/fleet'
import { SITE_COLORS, STATUS_COLORS, cssColor, label, seconds } from './theme'

export function StatusBadge({ status }: { status: RobotStatus }) {
  return (
    <Badge color={STATUS_COLORS[status]} variant="light">
      {label(status)}
    </Badge>
  )
}

export function SiteBadge({ status, ...props }: { status: SiteStatus } & BadgeProps) {
  return <Badge color={SITE_COLORS[status]} {...props}>{status}</Badge>
}

/** "updated 3s ago", ticking, so a stalled feed is visible. */
export function Updated({ at }: { at: number }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return (
    <Text size="xs" c="dimmed">
      updated {at ? seconds(Math.max(0, (now - at) / 1000)) : '…'}
    </Text>
  )
}

export function Stat({ title, value, hint }: { title: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Paper withBorder p="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{title}</Text>
      <Text component="div" fz={28} fw={700} mt={4}>{value}</Text>
      {hint && <Text size="xs" c="dimmed">{hint}</Text>}
    </Paper>
  )
}

// Positions are in each robot's own map frame. Sites have no map config yet,
// so the plot fits whatever positions it gets.
type Point = { x_m: number; y_m: number }

function bounds(points: Point[]) {
  const w = Math.max(10, ...points.map((p) => p.x_m)) * 1.05
  const h = Math.max(10, ...points.map((p) => p.y_m)) * 1.05
  return { w, h }
}

function Plot({ w, h, label, children }: { w: number; h: number; label: string; children: ReactNode }) {
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ display: 'block', width: '100%', aspectRatio: `${w} / ${h}` }} role="img" aria-label={label}>
      <rect width={w} height={h} rx={0.6} fill="var(--mantine-color-dark-7)" stroke="var(--mantine-color-dark-4)" strokeWidth={0.1} />
      {children}
    </svg>
  )
}

export function FloorMap({ robots }: { robots: Robot[] }) {
  const navigate = useNavigate()
  const placed = robots.filter((r): r is Robot & Point => r.x_m != null && r.y_m != null)
  const { w, h } = bounds(placed)
  return (
    <Plot w={w} h={h} label="robot positions">
      {placed.map((r) => (
        <Tooltip key={r.id} label={`${r.id} · ${label(r.status)}`} withArrow>
          <g style={{ cursor: 'pointer' }} onClick={() => navigate(`/robots/${r.id}`)}>
            <circle cx={r.x_m} cy={h - r.y_m} r={w / 70} fill={cssColor(STATUS_COLORS[r.status])} stroke="var(--mantine-color-dark-8)" strokeWidth={w / 400} />
            <text x={r.x_m + w / 50} y={h - r.y_m + w / 160} fontSize={w / 55} fill="var(--mantine-color-dark-1)">{r.id}</text>
          </g>
        </Tooltip>
      ))}
    </Plot>
  )
}

export function Trail({ points }: { points: Point[] }) {
  const { w, h } = bounds(points)
  const last = points[points.length - 1]
  return (
    <Plot w={w} h={h} label="position trail">
      <polyline
        points={points.map((p) => `${p.x_m},${h - p.y_m}`).join(' ')}
        fill="none"
        stroke="var(--mantine-color-teal-5)"
        strokeWidth={w / 400}
        strokeOpacity={0.7}
        strokeLinejoin="round"
      />
      {last && <circle cx={last.x_m} cy={h - last.y_m} r={w / 90} fill="var(--mantine-color-teal-4)" />}
    </Plot>
  )
}

export function Legend({ colors }: { colors: Record<string, string> }) {
  return (
    <Group gap="md">
      {Object.entries(colors).map(([k, c]) => (
        <Group key={k} gap={6}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: cssColor(c) }} />
          <Text size="xs" c="dimmed">{label(k)}</Text>
        </Group>
      ))}
    </Group>
  )
}

