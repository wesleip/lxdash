import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Play,
  Square,
  RefreshCw,
  Terminal,
  Camera,
  Trash2,
  Loader2,
  AlertCircle,
} from 'lucide-react'
import { containers } from '@/lib/api'
import type { ContainerStatus } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { cn, formatBytes, formatRelativeTime } from '@/lib/utils'

function statusVariant(
  status: ContainerStatus,
): 'success' | 'destructive' | 'secondary' | 'warning' | 'default' {
  switch (status) {
    case 'Running': return 'success'
    case 'Stopped': return 'secondary'
    case 'Frozen': return 'warning'
    case 'Error': return 'destructive'
    default: return 'default'
  }
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between py-2.5 border-b border-border last:border-0">
      <span className="text-sm text-muted-foreground min-w-[140px]">{label}</span>
      <span className="text-sm text-right font-medium">{value}</span>
    </div>
  )
}

export default function ContainerDetail() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState('overview')
  const [snapshotName, setSnapshotName] = useState('')

  const containerName = name!

  const containerQuery = useQuery({
    queryKey: ['containers', containerName],
    queryFn: ({ signal }) => containers.get(containerName, signal),
  })

  const stateQuery = useQuery({
    queryKey: ['containers', containerName, 'state'],
    queryFn: ({ signal }) => containers.getState(containerName, signal),
    refetchInterval: 5000,
    enabled: containerQuery.data?.status === 'Running',
  })

  const snapshotsQuery = useQuery({
    queryKey: ['containers', containerName, 'snapshots'],
    queryFn: ({ signal }) => containers.listSnapshots(containerName, signal),
    enabled: activeTab === 'snapshots',
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['containers', containerName] })
    void qc.invalidateQueries({ queryKey: ['containers'] })
  }

  const startMut = useMutation({ mutationFn: () => containers.start(containerName), onSettled: invalidate })
  const stopMut = useMutation({ mutationFn: () => containers.stop(containerName), onSettled: invalidate })
  const restartMut = useMutation({ mutationFn: () => containers.restart(containerName), onSettled: invalidate })
  const deleteMut = useMutation({
    mutationFn: () => containers.delete(containerName),
    onSuccess: () => navigate('/'),
  })
  const snapshotMut = useMutation({
    mutationFn: () => containers.createSnapshot(containerName, { name: snapshotName }),
    onSuccess: () => {
      setSnapshotName('')
      void qc.invalidateQueries({ queryKey: ['containers', containerName, 'snapshots'] })
    },
  })
  const deleteSnapshotMut = useMutation({
    mutationFn: (snap: string) => containers.deleteSnapshot(containerName, snap),
    onSettled: () =>
      qc.invalidateQueries({ queryKey: ['containers', containerName, 'snapshots'] }),
  })

  const container = containerQuery.data
  const state = stateQuery.data
  const isRunning = container?.status === 'Running'
  const isBusy = startMut.isPending || stopMut.isPending || restartMut.isPending || deleteMut.isPending

  if (containerQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-20 gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span>Loading…</span>
      </div>
    )
  }

  if (containerQuery.isError || !container) {
    return (
      <div className="flex items-center justify-center py-20 gap-2 text-destructive">
        <AlertCircle className="h-5 w-5" />
        <span>{(containerQuery.error as Error | null)?.message ?? 'Container not found'}</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold truncate">{container.name}</h1>
            <Badge variant={statusVariant(container.status)}>{container.status}</Badge>
          </div>
          {container.description && (
            <p className="text-muted-foreground text-sm mt-0.5">{container.description}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {isRunning ? (
            <Button variant="outline" size="sm" onClick={() => stopMut.mutate()} disabled={isBusy}>
              <Square className="h-3.5 w-3.5" />
              Stop
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => startMut.mutate()} disabled={isBusy}>
              <Play className="h-3.5 w-3.5" />
              Start
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => restartMut.mutate()}
            disabled={isBusy || !isRunning}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Restart
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(`/containers/${containerName}/console`)}
            disabled={!isRunning}
          >
            <Terminal className="h-3.5 w-3.5" />
            Console
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={() => {
              if (confirm(`Delete "${containerName}"? This cannot be undone.`)) {
                deleteMut.mutate()
              }
            }}
            disabled={isBusy || isRunning}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="resources">Resources</TabsTrigger>
          <TabsTrigger value="snapshots">Snapshots</TabsTrigger>
          <TabsTrigger value="config">Config</TabsTrigger>
        </TabsList>

        {/* Overview tab */}
        <TabsContent value="overview">
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">General</CardTitle>
              </CardHeader>
              <CardContent>
                <InfoRow label="Name" value={container.name} />
                <InfoRow label="Type" value={container.type} />
                <InfoRow label="Architecture" value={container.architecture} />
                <InfoRow label="Profiles" value={container.profiles.join(', ') || '—'} />
                <InfoRow label="Stateful" value={container.stateful ? 'Yes' : 'No'} />
                <InfoRow label="Created" value={formatRelativeTime(container.created_at)} />
                <InfoRow
                  label="Last used"
                  value={
                    container.last_used_at ? formatRelativeTime(container.last_used_at) : 'Never'
                  }
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Image</CardTitle>
              </CardHeader>
              <CardContent>
                <InfoRow label="OS" value={container.config['image.os'] ?? '—'} />
                <InfoRow label="Release" value={container.config['image.release'] ?? '—'} />
                <InfoRow label="Version" value={container.config['image.version'] ?? '—'} />
                <InfoRow label="Description" value={container.config['image.description'] ?? '—'} />
                <InfoRow label="Type" value={container.config['image.type'] ?? '—'} />
              </CardContent>
            </Card>

            {state?.network && (
              <Card className="md:col-span-2">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Network interfaces</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border text-muted-foreground">
                          <th className="text-left py-2 pr-4 font-medium">Interface</th>
                          <th className="text-left py-2 pr-4 font-medium">State</th>
                          <th className="text-left py-2 pr-4 font-medium">Addresses</th>
                          <th className="text-left py-2 pr-4 font-medium">MAC</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(state.network).map(([iface, info]) => (
                          <tr key={iface} className="border-b border-border last:border-0">
                            <td className="py-2 pr-4 font-mono text-xs">{iface}</td>
                            <td className="py-2 pr-4">
                              <Badge variant={info.state === 'up' ? 'success' : 'secondary'}>
                                {info.state}
                              </Badge>
                            </td>
                            <td className="py-2 pr-4 font-mono text-xs">
                              {info.addresses
                                .filter((a) => a.scope === 'global')
                                .map((a) => a.address)
                                .join(', ') || '—'}
                            </td>
                            <td className="py-2 pr-4 font-mono text-xs">{info.hwaddr}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Resources tab */}
        <TabsContent value="resources">
          {!isRunning ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
              Container must be running to view resource usage.
            </div>
          ) : stateQuery.isLoading ? (
            <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm">Loading state…</span>
            </div>
          ) : state ? (
            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">CPU</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {(state.cpu.usage / 1e9 / 1e3).toFixed(1)}s
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">Cumulative usage</p>
                  <InfoRow label="User time" value={`${(state.cpu.user_time / 1e9).toFixed(2)}s`} />
                  <InfoRow label="System time" value={`${(state.cpu.system_time / 1e9).toFixed(2)}s`} />
                  <InfoRow label="Processes" value={state.processes} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Memory</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{formatBytes(state.memory.usage)}</div>
                  <p className="text-xs text-muted-foreground mt-1">Current usage</p>
                  <InfoRow label="Peak" value={formatBytes(state.memory.usage_peak)} />
                  <InfoRow label="Swap" value={formatBytes(state.memory.swap_usage)} />
                  <InfoRow label="Swap peak" value={formatBytes(state.memory.swap_usage_peak)} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Disk</CardTitle>
                </CardHeader>
                <CardContent>
                  {Object.entries(state.disk).map(([disk, usage]) => (
                    <InfoRow
                      key={disk}
                      label={disk}
                      value={formatBytes(usage.usage)}
                    />
                  ))}
                </CardContent>
              </Card>
            </div>
          ) : null}
        </TabsContent>

        {/* Snapshots tab */}
        <TabsContent value="snapshots">
          <div className="space-y-4">
            {/* Create snapshot form */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Create snapshot</CardTitle>
              </CardHeader>
              <CardContent>
                <form
                  className="flex gap-3"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (snapshotName.trim()) snapshotMut.mutate()
                  }}
                >
                  <input
                    type="text"
                    placeholder="Snapshot name"
                    value={snapshotName}
                    onChange={(e) => setSnapshotName(e.target.value)}
                    className={cn(
                      'flex-1 h-9 rounded-md border border-input bg-background px-3 py-2 text-sm',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    )}
                  />
                  <Button
                    type="submit"
                    size="sm"
                    isLoading={snapshotMut.isPending}
                    disabled={!snapshotName.trim()}
                  >
                    <Camera className="h-3.5 w-3.5" />
                    Snapshot
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Snapshots list */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Snapshots</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                {snapshotsQuery.isLoading && (
                  <div className="flex items-center justify-center py-8 gap-2 text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span className="text-sm">Loading…</span>
                  </div>
                )}
                {snapshotsQuery.data?.length === 0 && (
                  <p className="text-center py-8 text-sm text-muted-foreground">
                    No snapshots yet.
                  </p>
                )}
                {snapshotsQuery.data && snapshotsQuery.data.length > 0 && (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-muted-foreground">
                        <th className="text-left px-4 py-2.5 font-medium">Name</th>
                        <th className="text-left px-4 py-2.5 font-medium">Created</th>
                        <th className="text-left px-4 py-2.5 font-medium">Stateful</th>
                        <th className="text-left px-4 py-2.5 font-medium">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshotsQuery.data.map((snap) => (
                        <tr key={snap.name} className="border-b border-border last:border-0">
                          <td className="px-4 py-3 font-medium">{snap.name}</td>
                          <td className="px-4 py-3 text-muted-foreground text-xs">
                            {formatRelativeTime(snap.created_at)}
                          </td>
                          <td className="px-4 py-3">
                            <Badge variant={snap.stateful ? 'success' : 'secondary'}>
                              {snap.stateful ? 'Yes' : 'No'}
                            </Badge>
                          </td>
                          <td className="px-4 py-3">
                            <Button
                              variant="ghost"
                              size="icon"
                              title="Delete snapshot"
                              className="text-muted-foreground hover:text-destructive"
                              onClick={() => {
                                if (confirm(`Delete snapshot "${snap.name}"?`)) {
                                  deleteSnapshotMut.mutate(snap.name)
                                }
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Config tab */}
        <TabsContent value="config">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Raw configuration</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-xs font-mono bg-muted rounded-md p-4 overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(container.config, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
