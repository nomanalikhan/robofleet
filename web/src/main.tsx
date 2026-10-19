import '@mantine/core/styles.css'
import '@mantine/charts/styles.css'

import { MantineProvider, createTheme } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import { HttpError } from './api/http'

const theme = createTheme({ primaryColor: 'teal', defaultRadius: 'md' })
// Retry once, but a 4xx will not get better.
const queries = new QueryClient({
  defaultOptions: {
    queries: { retry: (n, err) => n < 1 && !(err instanceof HttpError && err.status < 500) },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <QueryClientProvider client={queries}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
)
