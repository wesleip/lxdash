/**
 * API types for lxdash.
 *
 * These are hand-written interfaces that mirror the backend Pydantic schemas.
 * When a backend is running, replace this file with output from:
 *   npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts
 */

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export type UserRole = 'admin' | 'operator' | 'viewer'

export interface User {
  id: number
  username: string
  role: UserRole
  email: string | null
  is_active: boolean
  created_at: string
}

export interface UserCreate {
  username: string
  email: string
  password: string
  role: UserRole
}

export interface UserUpdate {
  email?: string
  role?: UserRole
  is_active?: boolean
}

export interface AuthToken {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export interface LoginRequest {
  username: string
  password: string
}

// ---------------------------------------------------------------------------
// Containers
// ---------------------------------------------------------------------------

export type ContainerStatus =
  | 'Running'
  | 'Stopped'
  | 'Frozen'
  | 'Error'
  | 'Starting'
  | 'Stopping'

export type ContainerType = 'container' | 'virtual-machine'

export interface ContainerNetwork {
  addresses: Array<{
    family: 'inet' | 'inet6'
    address: string
    netmask: string
    scope: 'global' | 'local' | 'link'
  }>
  counters: {
    bytes_received: number
    bytes_sent: number
    packets_received: number
    packets_sent: number
  }
  hwaddr: string
  host_name: string
  mtu: number
  state: 'up' | 'down'
  type: string
}

export interface ContainerCPUUsage {
  usage: number
  user_time: number
  system_time: number
}

export interface ContainerMemoryUsage {
  usage: number
  usage_peak: number
  swap_usage: number
  swap_usage_peak: number
}

export interface ContainerDiskUsage {
  usage: number
}

export interface ContainerState {
  status: ContainerStatus
  status_code: number
  cpu: ContainerCPUUsage
  memory: ContainerMemoryUsage
  disk: Record<string, ContainerDiskUsage>
  network: Record<string, ContainerNetwork> | null
  pid: number
  processes: number
}

export interface ContainerConfig {
  'image.architecture'?: string
  'image.description'?: string
  'image.label'?: string
  'image.os'?: string
  'image.release'?: string
  'image.serial'?: string
  'image.type'?: string
  'image.version'?: string
  'limits.cpu'?: string
  'limits.memory'?: string
  [key: string]: string | undefined
}

export interface Container {
  name: string
  description: string
  status: ContainerStatus
  type: ContainerType
  architecture: string
  config: ContainerConfig
  created_at: string
  last_used_at: string | null
  profiles: string[]
  stateful: boolean
  state?: ContainerState
}

export interface ContainerSummary {
  name: string
  status: ContainerStatus
  type: ContainerType
  ipv4: string | null
  ipv6: string | null
  image: string
  created_at: string
  last_used_at: string | null
}

export interface CreateContainerRequest {
  name: string
  image: string
  type?: ContainerType
  config?: ContainerConfig
  profiles?: string[]
  start_after_create?: boolean
}

export interface ContainerAction {
  action: 'start' | 'stop' | 'restart' | 'freeze' | 'unfreeze'
  timeout?: number
  force?: boolean
}

// ---------------------------------------------------------------------------
// Snapshots
// ---------------------------------------------------------------------------

export interface Snapshot {
  name: string
  created_at: string
  expires_at: string | null
  stateful: boolean
}

export interface CreateSnapshotRequest {
  name: string
  stateful?: boolean
  expires_at?: string
}

// ---------------------------------------------------------------------------
// Images
// ---------------------------------------------------------------------------

export interface ImageAlias {
  name: string
  description: string
}

export interface Image {
  fingerprint: string
  aliases: ImageAlias[]
  architecture: string
  public: boolean
  description: string
  os: string
  release: string
  variant: string
  type: 'container' | 'virtual-machine'
  size: number
  upload_date: string
  auto_update: boolean
  cached: boolean
}

export interface ImageSummary {
  fingerprint: string
  alias: string | null
  description: string
  os: string
  release: string
  architecture: string
  type: 'container' | 'virtual-machine'
  size: number
  upload_date: string
}

// ---------------------------------------------------------------------------
// Networks
// ---------------------------------------------------------------------------

export type NetworkType =
  | 'bridge'
  | 'macvlan'
  | 'sriov'
  | 'ovn'
  | 'physical'

export type NetworkState = 'Created' | 'Pending' | 'Errored' | 'Unknown'

export interface NetworkConfig {
  'ipv4.address'?: string
  'ipv4.nat'?: string
  'ipv4.dhcp'?: string
  'ipv6.address'?: string
  'ipv6.nat'?: string
  'ipv6.dhcp'?: string
  'bridge.mtu'?: string
  [key: string]: string | undefined
}

export interface Network {
  name: string
  description: string
  type: NetworkType
  status: NetworkState
  config: NetworkConfig
  managed: boolean
  used_by: string[]
}

export interface CreateNetworkRequest {
  name: string
  description?: string
  type?: NetworkType
  config?: NetworkConfig
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

export type StorageDriver =
  | 'btrfs'
  | 'ceph'
  | 'cephfs'
  | 'cephobject'
  | 'dir'
  | 'lvm'
  | 'lvmcluster'
  | 'zfs'

export type StoragePoolStatus = 'Created' | 'Pending' | 'Errored' | 'Unknown'

export interface StoragePoolConfig {
  'source'?: string
  'size'?: string
  'zfs.pool_name'?: string
  'lvm.vg_name'?: string
  [key: string]: string | undefined
}

export interface StoragePoolResource {
  inodes?: {
    used: number
    total: number
  }
  space: {
    used: number
    total: number
  }
}

export interface StoragePool {
  name: string
  description: string
  driver: StorageDriver
  status: StoragePoolStatus
  config: StoragePoolConfig
  used_by: string[]
  resources?: StoragePoolResource
}

export interface StorageVolume {
  name: string
  type: 'container' | 'virtual-machine' | 'image' | 'custom'
  pool: string
  config: Record<string, string>
  content_type: 'filesystem' | 'block'
  created_at: string
  used_by: string[]
}

// ---------------------------------------------------------------------------
// API response wrappers
// ---------------------------------------------------------------------------

export interface ApiError {
  detail: string
  status_code: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  has_next: boolean
}

// ---------------------------------------------------------------------------
// Hosts (the LXD registry every resource route delegates to)
// ---------------------------------------------------------------------------

export type ConnectionType = 'socket' | 'tls'

export interface Host {
  id: number
  name: string
  address: string
  connection_type: ConnectionType
  is_active: boolean
  created_at: string
}

export interface HostCreate {
  name: string
  address: string
  connection_type?: ConnectionType
  /** PEM-encoded client certificate. Required for `tls`, ignored for `socket`. */
  tls_cert?: string
  /** PEM-encoded client private key. Required for `tls`, ignored for `socket`. */
  tls_key?: string
  /** PEM-encoded server certificate to pin, when the host uses a private CA. */
  tls_server_cert?: string
}

/**
 * Answer of `GET /hosts/{id}/health`.
 *
 * A host that is down still answers 200 with `reachable: false` and a
 * `message`, so a fleet view can render one bad host instead of failing.
 */
export interface HostHealth {
  host_id: number
  host_name: string
  reachable: boolean
  address: string
  connection_type: ConnectionType
  api_version: string | null
  api_extensions_count: number | null
  server: string | null
  public: boolean | null
  auth: string | null
  auth_user_method: string | null
  clustered: boolean | null
  server_name: string | null
  certificate_fingerprint: string | null
  architecture: string | null
  os_name: string | null
  os_version: string | null
  hostname: string | null
  cpu_total: number | null
  memory_total: number | null
  message: string | null
}

export interface HostMetrics {
  host_id: number
  host_name: string
  reachable: boolean
  cpu_usage: number | null
  cpu_total: number | null
  memory_used: number | null
  memory_total: number | null
  disk_used: number | null
  disk_total: number | null
  network_bytes_received: number | null
  network_bytes_sent: number | null
  message: string | null
}

// ---------------------------------------------------------------------------
// Bootstrap (onboarding the local LXD daemon — admin-only)
// ---------------------------------------------------------------------------

/**
 * `unreachable` means the socket is missing or unreadable, which is not a
 * daemon state: no other answer would be truthful, and offering to bootstrap a
 * daemon we cannot see is the dead end this endpoint used to lead to.
 */
export type BootstrapState = 'unreachable' | 'uninitialized' | 'untrusted' | 'initialized'

export interface BootstrapStatus {
  state: BootstrapState
  api_version?: string | null
  server?: string | null
  /** `enabled: true` on /1.0/cluster — standalone daemons report false. */
  clustered?: boolean
  server_name?: string | null
  socket?: string | null
  /** Present when the local daemon already has a `hosts` row. */
  host_id?: number | null
  host_name?: string | null
  message?: string | null
}

export interface BootstrapClusterConfig {
  server_name: string
  cluster_password: string
}

export interface BootstrapRequest {
  host_name: string
  cluster: BootstrapClusterConfig
}

/** Body for adopting an already-initialized daemon. */
export interface BootstrapRegisterRequest {
  /** Defaults to the name LXD reports (`server_name`). */
  host_name?: string
}

export interface BootstrapResult {
  state: 'initialized'
  host_id: number
  host_name: string
  address: string
  connection_type: ConnectionType
  is_active: boolean
  created_at: string
}
