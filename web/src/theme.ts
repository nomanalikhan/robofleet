import dayjs from 'dayjs'
import type { XAxisProps } from 'recharts'
import relativeTime from 'dayjs/plugin/relativeTime'

import { GetActivityPeriod, RobotStatus, type SiteStatus, type TelemetryPointState } from './api/fleet'

dayjs.extend(relativeTime)

// Live views refetch every few seconds. Data lands every 10s, so this is fresh enough.
export const LIVE = { refetchInterval: 5_000 }

export const STATUS_COLORS: Record<RobotStatus, string> = {
  unknown: 'gray.7',
  offline: 'gray',
  error: 'red',
  stuck: 'orange',
  low_battery: 'yellow',
  ok: 'teal',
}

export const SITE_COLORS: Record<SiteStatus, string> = { online: 'teal', degraded: 'yellow', offline: 'red' }

export const STATE_COLORS: Record<TelemetryPointState, string> = {
  working: 'blue.5',
  charging: 'teal.5',
  idle: 'gray.5',
  returning: 'violet.5',
  paused: 'yellow.5',
  error: 'red.6',
}

export const STATUSES = Object.values(RobotStatus)
export const STATES = Object.keys(STATE_COLORS) as TelemetryPointState[]

export const PERIODS = Object.values(GetActivityPeriod)
const PERIOD_MS: Record<GetActivityPeriod, number> = { hour: 3_600_000, day: 86_400_000, week: 604_800_000, month: 2_592_000_000 }
const TICK: Record<GetActivityPeriod, string> = { hour: 'HH:mm', day: 'HH:mm', week: 'ddd HH:mm', month: 'MMM D' }

/** A time x-axis over the whole period up to `to`, so a short history sits at the right edge. */
export function timeAxis(period: GetActivityPeriod, to: number) {
  const from = to - PERIOD_MS[period]
  const ticks = Array.from({ length: 7 }, (_, i) => from + (i * (to - from)) / 6)
  return {
    from,
    to,
    xAxisProps: {
      type: 'number', scale: 'time', domain: [from, to], ticks, allowDataOverflow: true,
      tickFormatter: (t: number) => dayjs(t).format(TICK[period]),
    } satisfies XAxisProps,
  }
}
/** Refetch a chart about once per point, at most every 10s. */
export const chartRefetch = (q: { state: { data?: { bucket_s?: number | null } } }) =>
  Math.max(10, q.state.data?.bucket_s ?? 0) * 1000

export const bucketLabel = (s: number) => (s >= 3600 ? `${s / 3600} h` : `${s / 60} min`)

// The API already knows when a low battery is a problem, charging robots are not.
export const batteryColor = (problems: RobotStatus[]) => (problems.includes('low_battery') ? 'yellow' : 'teal')

export const label = (s: string) => s.replace('_', ' ')

/** A Mantine color like "teal.5" as a CSS variable, for SVG and plain styles. */
export const cssColor = (c: string) => {
  const [name, shade] = c.split('.')
  return `var(--mantine-color-${name}-${shade ?? 6})`
}

export function seconds(s: number | null | undefined) {
  if (s == null) return 'never'
  if (s < 90) return `${Math.round(s)}s ago`
  return dayjs().subtract(s, 'second').fromNow()
}
