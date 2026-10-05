import { useQuery } from '@tanstack/react-query'
import {
  Cpu,
  MemoryStick,
  HardDrive,
  Network,
  Container,
  Activity,
  Server,
  AlertTriangle,
} from 'lucide-react'
import { hosts, containers, storage } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LoadingState, ResourceError } from '@/components/common/ResourceState'
import { useActiveHostId } from '@/lib/hooks/useHosts'
import { formatBytes } from '@/lib/utils'

function MetricCard({
  title,
  icon: Icon,
  children,
}: {
  title: string
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

function ProgressBar({ value, max, variant = 'default' }: { value: number; max: number; variant?: 'default' | 'warning' | 'danger' }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  const color = variant === 'danger' ? 'bg-destructive' : variant === 'warning' ? 'bg-yellow-500' : 'bg-primary'
  return (
    <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function GaugeCard({
  label,
  used,
  total,
  icon: Icon,
}: {
  label: string
  used: number | null
  total: number | null
  icon: React.ComponentType<{ className?: string }>
}) {
  const hasData = used !== null && total !== null && total > 0
  const pct = hasData ? Math.min(100, Math.round((used / total) * 100)) : 0
  const variant = pct > 90 ? 'danger' : pct > 70 ? 'warning' : 'default'

  return (
    <MetricCard title={label} icon={Icon}>
      <div className="space-y-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold">
            {hasData ? formatBytes(used) : '—'}
          </span>
          <span className="text-sm text-muted-foreground">
            / {hasData ? formatBytes(total) : '—'}
          </span>
        </div>
        <ProgressBar value={used ?? 0} max={total ?? 0} variant={variant} />
        <p className="text-xs text-muted-foreground">
          {hasData ? `${pct}% used` : 'No data available'}
        </p>
      </div>
    </MetricCard>
  )
}

export default function Dashboard() {
  const hostId = useActiveHostId()

  const { data: health, isLoading: healthLoading, isError: healthError, error: healthErr } = useQuery({
    queryKey: ['host-health', hostId],
    queryFn: ({ signal }) => hosts.health(hostId!, signal),
    enabled: hostId !== null,
    // Back off to once a minute on failure so a permanently-unreachable
    // host does not spam the access log every 10s.
    refetchInterval: (q) => (q.state.status === 'error' ? 60_000 : 10_000),
  })

  const { data: containerList, isLoading: containersLoading } = useQuery({
    queryKey: ['containers', hostId],
    queryFn: ({ signal }) => containers.list(hostId, signal),
    enabled: hostId !== null,
    refetchInterval: (q) => (q.state.status === 'error' ? 60_000 : 10_000),
  })

  const { data: storagePools, isLoading: storageLoading } = useQuery({
    queryKey: ['storage', hostId],
    queryFn: ({ signal }) => storage.list(hostId, signal),
    enabled: hostId !== null,
    refetchInterval: (q) => (q.state.status === 'error' ? 60_000 : 30_000),
  })

  const isLoading = healthLoading || containersLoading || storageLoading
  const isError = healthError
  const error = healthErr

  const runningContainers = containerList?.filter((c) => c.status === 'Running').length ?? 0
  const stoppedContainers = containerList?.filter((c) => c.status === 'Stopped').length ?? 0
  const totalContainers = containerList?.length ?? 0

  const totalDisk = storagePools?.reduce((acc, pool) => acc + (pool.resources?.space?.total ?? 0), 0) ?? 0
  const usedDisk = storagePools?.reduce((acc, pool) => acc + (pool.resources?.space?.used ?? 0), 0) ?? 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground text-sm">Host monitoring overview</p>
      </div>

      {isLoading && <LoadingState label="Loading host metrics…" />}

      {isError && <ResourceError error={error} />}

      {!isLoading && !isError && health && (
        <>
          {!health.reachable && (
            <Card className="border-destructive/50 bg-destructive/5">
              <CardContent className="flex items-center gap-3 pt-6">
                <AlertTriangle className="h-5 w-5 text-destructive" />
                <div>
                  <p className="font-medium text-destructive">Host unreachable</p>
                  <p className="text-sm text-muted-foreground">{health.message}</p>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard title="Host" icon={Server}>
              <div className="space-y-2">
                <p className="text-lg font-semibold truncate">{health.host_name}</p>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">{health.architecture ?? 'Unknown'}</Badge>
                  {health.clustered && <Badge variant="secondary">Clustered</Badge>}
                </div>
                <p className="text-xs text-muted-foreground">
                  {health.os_name} {health.os_version}
                </p>
              </div>
            </MetricCard>

            <MetricCard title="Containers" icon={Container}>
              <div className="space-y-2">
                <p className="text-2xl font-bold">{totalContainers}</p>
                <div className="flex gap-3 text-sm">
                  <span className="text-green-600 dark:text-green-400">{runningContainers} running</span>
                  <span className="text-muted-foreground">{stoppedContainers} stopped</span>
                </div>
              </div>
            </MetricCard>

            <MetricCard title="CPU" icon={Cpu}>
              <div className="space-y-2">
                <p className="text-2xl font-bold">{health.cpu_total ?? '—'}</p>
                <p className="text-xs text-muted-foreground">cores</p>
              </div>
            </MetricCard>

            <MetricCard title="Memory" icon={MemoryStick}>
              <div className="space-y-2">
                <p className="text-2xl font-bold">
                  {health.memory_total ? formatBytes(health.memory_total) : '—'}
                </p>
                <p className="text-xs text-muted-foreground">total RAM</p>
              </div>
            </MetricCard>
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            <GaugeCard
              label="Disk Usage"
              used={usedDisk}
              total={totalDisk}
              icon={HardDrive}
            />

            <MetricCard title="Storage Pools" icon={HardDrive}>
              <div className="space-y-3">
                {storagePools?.map((pool) => {
                  const used = pool.resources?.space?.used ?? 0
                  const total = pool.resources?.space?.total ?? 0
                  const pct = total > 0 ? Math.round((used / total) * 100) : 0
                  return (
                    <div key={pool.name} className="space-y-1">
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-medium truncate">{pool.name}</span>
                        <span className="text-muted-foreground text-xs">{pct}%</span>
                      </div>
                      <ProgressBar value={used} max={total} variant={pct > 90 ? 'danger' : pct > 70 ? 'warning' : 'default'} />
                    </div>
                  )
                }) ?? <p className="text-sm text-muted-foreground">No storage pools</p>}
              </div>
            </MetricCard>

            <MetricCard title="Network" icon={Network}>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  Network metrics are available per container.
                </p>
                <p className="text-xs text-muted-foreground">
                  LXD does not expose host-level network counters via the REST API.
                </p>
              </div>
            </MetricCard>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <MetricCard title="API Info" icon={Activity}>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">API Version</span>
                  <span className="font-mono">{health.api_version ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Extensions</span>
                  <span>{health.api_extensions_count ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Server</span>
                  <span>{health.server ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Auth</span>
                  <span>{health.auth ?? '—'}</span>
                </div>
              </div>
            </MetricCard>

            <MetricCard title="System" icon={Server}>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Hostname</span>
                  <span>{health.hostname ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">OS</span>
                  <span>{health.os_name ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Version</span>
                  <span>{health.os_version ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Clustered</span>
                  <span>{health.clustered ? 'Yes' : 'No'}</span>
                </div>
              </div>
            </MetricCard>
          </div>
        </>
      )}
    </div>
  )
}
