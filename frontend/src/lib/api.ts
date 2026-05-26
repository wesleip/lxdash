/**
 * Typed API client for lxdash.
 *
 * Rules:
 * - Never call fetch directly in components — always through React Query using
 *   these functions.
 * - JWT token is read from localStorage on every request so Zustand auth store
 *   stays in sync without coupling the client to the store.
 * - 401 responses redirect to /login.
 */

import type {
  AuthToken,
  Container,
  ContainerSummary,
  ContainerState,
  ContainerAction,
  CreateContainerRequest,
  Snapshot,
  CreateSnapshotRequest,
  Image,
  ImageSummary,
  Network,
  CreateNetworkRequest,
  StoragePool,
  LoginRequest,
} from '@/types/api'

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

const BASE_URL = '/api'

function getToken(): string | null {
  try {
    return localStorage.getItem('lxdash_token')
  } catch {
    return null
  }
}

function buildHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extra,
  }
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const url = `${BASE_URL}${path}`
  const response = await fetch(url, {
    method,
    headers: buildHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })

  if (response.status === 401) {
    // Clear stale token and redirect to login
    localStorage.removeItem('lxdash_token')
    window.location.href = '/login'
    // This promise will never resolve as the page is redirecting
    return new Promise(() => {})
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const data = await response.json()
      detail = data?.detail ?? detail
    } catch {
      // ignore parse error
    }
    throw new ApiError(response.status, detail)
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as unknown as T
  }

  return response.json() as Promise<T>
}

const get = <T>(path: string, signal?: AbortSignal) =>
  request<T>('GET', path, undefined, signal)

const post = <T>(path: string, body?: unknown, signal?: AbortSignal) =>
  request<T>('POST', path, body, signal)

const put = <T>(path: string, body?: unknown, signal?: AbortSignal) =>
  request<T>('PUT', path, body, signal)

const patch = <T>(path: string, body?: unknown, signal?: AbortSignal) =>
  request<T>('PATCH', path, body, signal)

const del = <T>(path: string, signal?: AbortSignal) =>
  request<T>('DELETE', path, undefined, signal)

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const auth = {
  login: async (credentials: LoginRequest): Promise<AuthToken> => {
    // Backend uses OAuth2PasswordRequestForm — must be form-urlencoded, not JSON.
    const body = new URLSearchParams({
      username: credentials.username,
      password: credentials.password,
    })
    const response = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
    if (!response.ok) {
      let detail = `HTTP ${response.status}`
      try { detail = (await response.json())?.detail ?? detail } catch { /* ignore */ }
      throw new ApiError(response.status, detail)
    }
    return response.json()
  },

  logout: (): Promise<void> => post<void>('/auth/logout'),

  me: (signal?: AbortSignal): Promise<AuthToken['user']> =>
    get('/auth/me', signal),
}

// ---------------------------------------------------------------------------
// Containers
// ---------------------------------------------------------------------------

export const containers = {
  list: (signal?: AbortSignal): Promise<ContainerSummary[]> =>
    get<ContainerSummary[]>('/containers', signal),

  get: (name: string, signal?: AbortSignal): Promise<Container> =>
    get<Container>(`/containers/${name}`, signal),

  getState: (name: string, signal?: AbortSignal): Promise<ContainerState> =>
    get<ContainerState>(`/containers/${name}/state`, signal),

  create: (data: CreateContainerRequest): Promise<Container> =>
    post<Container>('/containers', data),

  delete: (name: string): Promise<void> =>
    del<void>(`/containers/${name}`),

  start: (name: string): Promise<void> =>
    put<void>(`/containers/${name}/state`, {
      action: 'start',
      timeout: 30,
    } satisfies ContainerAction),

  stop: (name: string, force = false): Promise<void> =>
    put<void>(`/containers/${name}/state`, {
      action: 'stop',
      timeout: 30,
      force,
    } satisfies ContainerAction),

  restart: (name: string, force = false): Promise<void> =>
    put<void>(`/containers/${name}/state`, {
      action: 'restart',
      timeout: 30,
      force,
    } satisfies ContainerAction),

  freeze: (name: string): Promise<void> =>
    put<void>(`/containers/${name}/state`, {
      action: 'freeze',
    } satisfies ContainerAction),

  unfreeze: (name: string): Promise<void> =>
    put<void>(`/containers/${name}/state`, {
      action: 'unfreeze',
    } satisfies ContainerAction),

  // Snapshots
  listSnapshots: (name: string, signal?: AbortSignal): Promise<Snapshot[]> =>
    get<Snapshot[]>(`/containers/${name}/snapshots`, signal),

  createSnapshot: (
    name: string,
    data: CreateSnapshotRequest,
  ): Promise<Snapshot> =>
    post<Snapshot>(`/containers/${name}/snapshots`, data),

  deleteSnapshot: (name: string, snapshotName: string): Promise<void> =>
    del<void>(`/containers/${name}/snapshots/${snapshotName}`),

  restoreSnapshot: (name: string, snapshotName: string): Promise<void> =>
    post<void>(`/containers/${name}/snapshots/${snapshotName}/restore`),

  // Exec
  exec: (
    name: string,
    command: string[],
    interactive = false,
  ): Promise<{ operation: string; fds: Record<string, string> }> =>
    post(`/containers/${name}/exec`, { command, interactive }),
}

// ---------------------------------------------------------------------------
// Images
// ---------------------------------------------------------------------------

export const images = {
  list: (signal?: AbortSignal): Promise<ImageSummary[]> =>
    get<ImageSummary[]>('/images', signal),

  get: (fingerprint: string, signal?: AbortSignal): Promise<Image> =>
    get<Image>(`/images/${fingerprint}`, signal),

  delete: (fingerprint: string): Promise<void> =>
    del<void>(`/images/${fingerprint}`),

  refresh: (fingerprint: string): Promise<void> =>
    post<void>(`/images/${fingerprint}/refresh`),
}

// ---------------------------------------------------------------------------
// Networks
// ---------------------------------------------------------------------------

export const networks = {
  list: (signal?: AbortSignal): Promise<Network[]> =>
    get<Network[]>('/networks', signal),

  get: (name: string, signal?: AbortSignal): Promise<Network> =>
    get<Network>(`/networks/${name}`, signal),

  create: (data: CreateNetworkRequest): Promise<Network> =>
    post<Network>('/networks', data),

  update: (name: string, data: Partial<CreateNetworkRequest>): Promise<Network> =>
    patch<Network>(`/networks/${name}`, data),

  delete: (name: string): Promise<void> =>
    del<void>(`/networks/${name}`),
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

export const storage = {
  list: (signal?: AbortSignal): Promise<StoragePool[]> =>
    get<StoragePool[]>('/storage', signal),

  get: (name: string, signal?: AbortSignal): Promise<StoragePool> =>
    get<StoragePool>(`/storage/${name}`, signal),

  create: (data: {
    name: string
    driver: string
    config?: Record<string, string>
  }): Promise<StoragePool> => post<StoragePool>('/storage', data),

  delete: (name: string): Promise<void> =>
    del<void>(`/storage/${name}`),
}

// Re-export error class so callers can do `instanceof ApiError`
export { ApiError }
