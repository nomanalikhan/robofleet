/** Thrown for any non-2xx response, so a 404 is an error and not an empty page. */
export class HttpError extends Error {
  constructor(public status: number, public detail: string) {
    super(`${status}: ${detail}`)
    this.name = 'HttpError'
  }
}

export async function http<T>(url: string, options: RequestInit): Promise<T> {
  const res = await fetch(url, options)
  const body = [204, 205, 304].includes(res.status) ? null : await res.text()
  if (!res.ok) {
    let detail = body || res.statusText
    try {
      const d = body && JSON.parse(body).detail
      if (typeof d === 'string') detail = d
    } catch {
      // not JSON, the raw text is the best detail we have
    }
    throw new HttpError(res.status, detail)
  }
  return body ? JSON.parse(body) : (null as T)
}
