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
      // explode sends list filters as repeated params, ?status=error&status=stuck.
      override: {
        mutator: { path: 'src/api/http.ts', name: 'http' },
        fetch: { includeHttpResponseReturnType: false, explode: true },
      },
    },
  },
})
