import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadReport, setAccessToken } from '../src/lib/api'

describe('report downloads', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessToken(null)
  })

  it('carries the Authorization header and parses the server filename', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/reports/scan-1/pdf')
      expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer t1')
      // jsdom's Blob is not stream()-able by Node's Response — pass bytes directly.
      return new Response(new Uint8Array([37, 80, 68, 70]), {
        status: 200,
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': 'attachment; filename="wardress-report-example-abcd1234.pdf"',
        },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:fake'),
      revokeObjectURL: vi.fn(),
    })

    setAccessToken('t1')
    const { url, filename } = await downloadReport('scan-1', 'pdf')
    expect(url).toBe('blob:fake')
    expect(filename).toBe('wardress-report-example-abcd1234.pdf')
  })

  it('falls back to a sane filename when the header is missing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('# report', { status: 200 }))
    )
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:fake'),
      revokeObjectURL: vi.fn(),
    })
    const { filename } = await downloadReport('scan-1', 'markdown')
    expect(filename).toBe('wardress-report.md')
  })
})
