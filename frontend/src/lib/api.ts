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
  User,
  UserCreate,
  UserUpdate,
  Host,
  HostCreate,
  HostHealth,
  HostMetrics,
  BootstrapRequest,
  BootstrapRegisterRequest,
  BootstrapResult,
  BootstrapStatus,
} from '@/types/api'

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

const BASE_URL = '/api'

/**
 * Every LXD-scoped endpoint is served by a `hosts` row. `null` means "let the
 * backend pick": it falls back to the single registered host and answers 422 if
 * more than one exists, which is the right default for a single-host install.
 */
export type HostId = number | null

/** Append `host_id` to *path* unless the caller deferred to the backend. */
function hostPath(path: string, hostId: HostId): string {
  return hostId === null ? path : `${path}?host_id=${hostId}`
}

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
    // API responses are never safe to reuse. Without this, the browser may
    // serve a stale `[]` from a previous visit even though the DB now has
    // rows.
    cache: 'no-store',
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
  list: (hostId: HostId, signal?: AbortSignal): Promise<ContainerSummary[]> =>
    get<ContainerSummary[]>(hostPath('/containers', hostId), signal),

  get: (hostId: HostId, name: string, signal?: AbortSignal): Promise<Container> =>
    get<Container>(hostPath(`/containers/${name}`, hostId), signal),

  getState: (hostId: HostId, name: string, signal?: AbortSignal): Promise<ContainerState> =>
    get<ContainerState>(hostPath(`/containers/${name}/state`, hostId), signal),

  create: (hostId: HostId, data: CreateContainerRequest): Promise<Container> =>
    post<Container>(hostPath('/containers', hostId), data),

  delete: (hostId: HostId, name: string): Promise<void> =>
    del<void>(hostPath(`/containers/${name}`, hostId)),

  // The backend exposes one route per action (POST /start|stop|restart);
  // PUT /containers/{name}/state does not exist and returned 404.
  start: (hostId: HostId, name: string): Promise<void> =>
    post<void>(hostPath(`/containers/${name}/start`, hostId), { timeout: 30 }),

  stop: (hostId: HostId, name: string, force = false): Promise<void> =>
    post<void>(hostPath(`/containers/${name}/stop`, hostId), { timeout: 30, force }),

  restart: (hostId: HostId, name: string, force = false): Promise<void> =>
    post<void>(hostPath(`/containers/${name}/restart`, hostId), { timeout: 30, force }),

  freeze: (hostId: HostId, name: string): Promise<void> =>
    put<void>(hostPath(`/containers/${name}/state`, hostId), {
      action: 'freeze',
    } satisfies ContainerAction),

  unfreeze: (hostId: HostId, name: string): Promise<void> =>
    put<void>(hostPath(`/containers/${name}/state`, hostId), {
      action: 'unfreeze',
    } satisfies ContainerAction),

  // Snapshots
  listSnapshots: (
    hostId: HostId,
    name: string,
    signal?: AbortSignal,
  ): Promise<Snapshot[]> =>
    get<Snapshot[]>(hostPath(`/containers/${name}/snapshots`, hostId), signal),

  createSnapshot: (
    hostId: HostId,
    name: string,
    data: CreateSnapshotRequest,
  ): Promise<Snapshot> =>
    post<Snapshot>(hostPath(`/containers/${name}/snapshots`, hostId), data),

  deleteSnapshot: (hostId: HostId, name: string, snapshotName: string): Promise<void> =>
    del<void>(hostPath(`/containers/${name}/snapshots/${snapshotName}`, hostId)),

  restoreSnapshot: (hostId: HostId, name: string, snapshotName: string): Promise<void> =>
    post<void>(hostPath(`/containers/${name}/snapshots/${snapshotName}/restore`, hostId)),

  // Exec
  exec: (
    hostId: HostId,
    name: string,
    command: string[],
    interactive = false,
  ): Promise<{ operation: string; fds: Record<string, string> }> =>
    post(hostPath(`/containers/${name}/exec`, hostId), { command, interactive }),
}

// ---------------------------------------------------------------------------
// Images
// ---------------------------------------------------------------------------

export const images = {
  list: (hostId: HostId, signal?: AbortSignal): Promise<ImageSummary[]> =>
    get<ImageSummary[]>(hostPath('/images', hostId), signal),

  get: (hostId: HostId, fingerprint: string, signal?: AbortSignal): Promise<Image> =>
    get<Image>(hostPath(`/images/${fingerprint}`, hostId), signal),

  delete: (hostId: HostId, fingerprint: string): Promise<void> =>
    del<void>(hostPath(`/images/${fingerprint}`, hostId)),

  refresh: (hostId: HostId, fingerprint: string): Promise<void> =>
    post<void>(hostPath(`/images/${fingerprint}/refresh`, hostId)),
}

// ---------------------------------------------------------------------------
// Networks
// ---------------------------------------------------------------------------

export const networks = {
  list: (hostId: HostId, signal?: AbortSignal): Promise<Network[]> =>
    get<Network[]>(hostPath('/networks', hostId), signal),

  get: (hostId: HostId, name: string, signal?: AbortSignal): Promise<Network> =>
    get<Network>(hostPath(`/networks/${name}`, hostId), signal),

  create: (hostId: HostId, data: CreateNetworkRequest): Promise<Network> =>
    post<Network>(hostPath('/networks', hostId), data),

  update: (
    hostId: HostId,
    name: string,
    data: Partial<CreateNetworkRequest>,
  ): Promise<Network> =>
    patch<Network>(hostPath(`/networks/${name}`, hostId), data),

  delete: (hostId: HostId, name: string): Promise<void> =>
    del<void>(hostPath(`/networks/${name}`, hostId)),
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

export const storage = {
  list: (hostId: HostId, signal?: AbortSignal): Promise<StoragePool[]> =>
    get<StoragePool[]>(hostPath('/storage', hostId), signal),

  get: (hostId: HostId, name: string, signal?: AbortSignal): Promise<StoragePool> =>
    get<StoragePool>(hostPath(`/storage/${name}`, hostId), signal),

  create: (
    hostId: HostId,
    data: {
      name: string
      driver: string
      config?: Record<string, string>
    },
  ): Promise<StoragePool> => post<StoragePool>(hostPath('/storage', hostId), data),

  delete: (hostId: HostId, name: string): Promise<void> =>
    del<void>(hostPath(`/storage/${name}`, hostId)),
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export const users = {
  list: (signal?: AbortSignal): Promise<User[]> =>
    get<User[]>('/users', signal),

  create: (data: UserCreate): Promise<User> =>
    post<User>('/users', data),

  update: (id: number, data: UserUpdate): Promise<User> =>
    patch<User>(`/users/${id}`, data),

  resetPassword: (id: number, password: string): Promise<void> =>
    post<void>(`/users/${id}/reset-password`, { password }),

  delete: (id: number): Promise<void> =>
    del<void>(`/users/${id}`),
}

// ---------------------------------------------------------------------------
// Hosts
// ---------------------------------------------------------------------------

export const hosts = {
  list: (signal?: AbortSignal): Promise<Host[]> =>
    get<Host[]>('/hosts', signal),

  /**
   * Register a host. The backend probes the LXD REST API first and answers 502
   * when the address is wrong, so a typo cannot be stored.
   */
  create: (data: HostCreate): Promise<Host> =>
    post<Host>('/hosts', data),

  remove: (hostId: number): Promise<void> =>
    del<void>(`/hosts/${hostId}`),

  health: (hostId: number, signal?: AbortSignal): Promise<HostHealth> =>
    get<HostHealth>(`/hosts/${hostId}/health`, signal),

  metrics: (hostId: number, signal?: AbortSignal): Promise<HostMetrics> =>
    get<HostMetrics>(`/hosts/${hostId}/metrics`, signal),
}

// ---------------------------------------------------------------------------
// Bootstrap (local LXD onboarding — admin-only)
// ---------------------------------------------------------------------------

export const bootstrap = {
  status: (signal?: AbortSignal): Promise<BootstrapStatus> =>
    get<BootstrapStatus>('/bootstrap/status', signal),

  /**
   * Adopt an already-initialized daemon. This is the flow for a host that
   * already runs containers: nothing is bootstrapped, a `hosts` row is created.
   * Idempotent — a second call returns 200 with the existing host.
   */
  register: (data: BootstrapRegisterRequest = {}): Promise<BootstrapResult> =>
    post<BootstrapResult>('/bootstrap/register', data),

  /** Create the first node of a brand-new cluster. */
  cluster: (data: BootstrapRequest): Promise<BootstrapResult> =>
    post<BootstrapResult>('/bootstrap/cluster', data),
}

// Re-export error class so callers can do `instanceof ApiError`
export { ApiError }
