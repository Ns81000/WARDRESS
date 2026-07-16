import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../src/App'

describe('App shell', () => {
  it('renders the Wardress placeholder', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Wardress' })).toBeDefined()
    expect(screen.getByText(/Phase 0 stack online/)).toBeDefined()
  })
})
