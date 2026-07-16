import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App'
import { AuthProvider } from '../src/lib/auth'

function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('App', () => {
  beforeEach(() => {
    // No session: the boot-time silent refresh comes back 401.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'No refresh token' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('redirects unauthenticated visitors to the login screen', async () => {
    renderApp('/')
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Wardress' })).toBeDefined()
    })
    expect(screen.getByLabelText('Email')).toBeDefined()
    expect(screen.getByLabelText('Password')).toBeDefined()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDefined()
  })

  it('shows the tagline on the login screen', async () => {
    renderApp('/login')
    await waitFor(() => {
      expect(
        screen.getByText('The watch that never stands down.')
      ).toBeDefined()
    })
  })
})
