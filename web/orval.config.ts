import { defineConfig } from 'orval'

// Typed fetch functions and React Query hooks generated from the Fleet API spec.
// Regenerate with `npm run gen:api` while the API runs.
export default defineConfig({
  fleet: {
    input: 'http://localhost:8000/openapi.json',
    output: {
      target: 'src/api/fleet.ts',
      client: 'react-query',
      httpClient: 'fetch',
      override: { fetch: { includeHttpResponseReturnType: false } },
    },
  },
})
