import { Alert, Anchor, AppShell, Burger, Group, NavLink, Stack, Text, Title } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconBuildingFactory2, IconRobot } from '@tabler/icons-react'
import { Component, useEffect, type ReactNode } from 'react'
import { Link, Navigate, NavLink as RouterLink, Route, Routes, useLocation } from 'react-router-dom'

import { useListSites } from './api/fleet'
import { LIVE } from './theme'
import { SiteBadge } from './ui'
import RobotPage from './pages/RobotPage'
import RobotsPage from './pages/RobotsPage'
import SitePage from './pages/SitePage'

export default function App() {
  const sites = useListSites({ query: LIVE })
  const first = sites.data?.[0]?.id
  const [opened, { toggle, close }] = useDisclosure()
  const { pathname } = useLocation()
  useEffect(close, [pathname, close])

  return (
    <AppShell
      // The header only exists on small screens, where it holds the burger.
      header={{ height: { base: 48, sm: 0 } }}
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header hiddenFrom="sm" px="md">
        <Group h="100%" gap="sm">
          <Burger opened={opened} onClick={toggle} size="sm" aria-label="Toggle navigation" />
          <Title order={4}>RoboFleet</Title>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="md">
        <Stack gap="xs">
          <Title order={4} mb="sm" visibleFrom="sm">RoboFleet</Title>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Sites</Text>
          {sites.data?.map((s) => (
            <NavLink
              key={s.id}
              component={RouterLink}
              to={`/sites/${s.id}`}
              label={s.id}
              leftSection={<IconBuildingFactory2 size={18} />}
              rightSection={<SiteBadge size="xs" variant="dot" status={s.status} />}
            />
          ))}
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} mt="md">Fleet</Text>
          <NavLink component={RouterLink} to="/robots" end label="All robots" leftSection={<IconRobot size={18} />} />
        </Stack>
      </AppShell.Navbar>
      <AppShell.Main>
        <ErrorBoundary key={pathname}>
          <Routes>
            <Route path="/" element={first ? <Navigate to={`/sites/${first}`} replace /> : <Group>Loading sites…</Group>} />
            <Route path="/sites/:siteId" element={<SitePage />} />
            <Route path="/robots" element={<RobotsPage />} />
            <Route path="/robots/:robotId" element={<RobotPage />} />
          </Routes>
        </ErrorBoundary>
      </AppShell.Main>
    </AppShell>
  )
}

// Keyed on the path, so navigating away from a broken page resets it.
class ErrorBoundary extends Component<{ children: ReactNode }, { error?: Error }> {
  state: { error?: Error } = {}
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <Alert color="red" title="Something went wrong">
        {this.state.error.message} <Anchor component={Link} to="/">Back to the fleet</Anchor>
      </Alert>
    )
  }
}
