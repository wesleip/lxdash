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

export interface User {
  id: number
  username: string
  role: 'admin' | 'operator' | 'viewer'
  email: string | null
  is_active: boolean
  created_at: string
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
