import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import Hosts from '@/pages/Hosts'
import * as api from '@/lib/api'

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof api>('@/lib/api')
  return {
    ...actual,
    hosts: {
      list: vi.fn(),
      create: vi.fn(),
      remove: vi.fn(),
      health: vi.fn(),
      metrics: vi.fn(),
    },
  }
})

vi.mock('@/store/auth', () => ({
  useAuthStore: vi.fn((selector) =>
    selector({ user: { username: 'admin', role: 'admin' }, token: 'fake', setAuth: () => {}, logout: () => {}, isAuthenticated: () => true }),
  ),
}))

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
}

describe('Hosts page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders hosts returned by the API', async () => {
    ;(api.hosts.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 1,
        name: 'node1',
        address: '/var/snap/lxd/common/lxd/unix.socket',
        connection_type: 'socket',
        is_active: true,
        created_at: new Date().toISOString(),
      },
    ])
    ;(api.hosts.health as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      host_id: 1,
      host_name: 'node1',
      reachable: true,
      address: '/var/snap/lxd/common/lxd/unix.socket',
      connection_type: 'socket',
      api_version: '1.0',
      clustered: false,
    })

    render(<Hosts />, { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(screen.getByText('node1')).toBeInTheDocument()
    })

    expect(screen.getByText('LXD hosts')).toBeInTheDocument()
    expect(screen.getByText('/var/snap/lxd/common/lxd/unix.socket')).toBeInTheDocument()
  })

  it('shows the empty state when the API returns []', async () => {
    ;(api.hosts.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([])

    render(<Hosts />, { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(screen.getByText(/No hosts registered yet/i)).toBeInTheDocument()
    })
  })

  it('calls hosts.list again when the manual refresh button is clicked', async () => {
    const list = api.hosts.list as unknown as ReturnType<typeof vi.fn>
    list.mockResolvedValue([])

    render(<Hosts />, { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(screen.getByText(/No hosts registered yet/i)).toBeInTheDocument()
    })

    // refetchOnMount: 'always' triggers a fetch on mount, plus React Query
    // may also fire a second call during the empty-state render. From this
    // point on the user-driven refresh must increase the count.
    const before = list.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))
    await waitFor(() => {
      expect(list.mock.calls.length).toBeGreaterThan(before)
    })
  })
})