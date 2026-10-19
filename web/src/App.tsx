import { AppShell, Group, NavLink, Stack, Text, Title } from '@mantine/core'
import { IconBuildingFactory2, IconRobot } from '@tabler/icons-react'
import { Navigate, NavLink as RouterLink, Route, Routes } from 'react-router-dom'

import { useListSites } from './api/fleet'
import { LIVE } from './theme'
import { SiteBadge } from './ui'
import RobotPage from './pages/RobotPage'
import RobotsPage from './pages/RobotsPage'
import SitePage from './pages/SitePage'

export default function App() {
  const sites = useListSites({ query: LIVE })
  const first = sites.data?.[0]?.id

  return (
    <AppShell navbar={{ width: 240, breakpoint: 'sm' }} padding="lg">
      <AppShell.Navbar p="md">
        <Stack gap="xs">
          <Title order={4} mb="sm">Olivaw Fleet</Title>
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
        <Routes>
          <Route path="/" element={first ? <Navigate to={`/sites/${first}`} replace /> : <Group>Loading sites…</Group>} />
          <Route path="/sites/:siteId" element={<SitePage />} />
          <Route path="/robots" element={<RobotsPage />} />
          <Route path="/robots/:robotId" element={<RobotPage />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  )
}
