import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Play,
  Square,
  RefreshCw,
  Trash2,
  Terminal,
  AlertCircle,
  Loader2,
  Plus,
} from 'lucide-react'
import { containers } from '@/lib/api'
import type { ContainerSummary, ContainerStatus } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn, formatRelativeTime, formatIpv4 } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function statusVariant(
  status: ContainerStatus,
): 'success' | 'destructive' | 'secondary' | 'warning' | 'default' {
  switch (status) {
    case 'Running':
      return 'success'
    case 'Stopped':
      return 'secondary'
    case 'Frozen':
      return 'warning'
    case 'Error':
      return 'destructive'
    default:
      return 'default'
  }
}

// ---------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------

interface RowActionsProps {
  container: ContainerSummary
  onMutate: () => void
}

function RowActions({ container, onMutate }: RowActionsProps) {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['containers'] })
    onMutate()
  }

  const startMut = useMutation({
    mutationFn: () => containers.start(container.name),
    onSettled: invalidate,
  })
  const stopMut = useMutation({
    mutationFn: () => containers.stop(container.name),
    onSettled: invalidate,
  })
  const restartMut = useMutation({
    mutationFn: () => containers.restart(container.name),
    onSettled: invalidate,
  })
  const deleteMut = useMutation({
    mutationFn: () => containers.delete(container.name),
    onSettled: invalidate,
  })

  const isRunning = container.status === 'Running'
  const isBusy =
    startMut.isPending ||
    stopMut.isPending ||
    restartMut.isPending ||
    deleteMut.isPending

  return (
    <div className="flex items-center gap-1">
      {isRunning ? (
        <Button
          variant="ghost"
          size="icon"
          title="Stop"
          onClick={() => stopMut.mutate()}
          disabled={isBusy}
        >
          <Square className="h-3.5 w-3.5" />
        </Button>
      ) : (
        <Button
          variant="ghost"
          size="icon"
          title="Start"
          onClick={() => startMut.mutate()}
          disabled={isBusy}
        >
          <Play className="h-3.5 w-3.5" />
        </Button>
      )}

      <Button
        variant="ghost"
        size="icon"
        title="Restart"
        onClick={() => restartMut.mutate()}
        disabled={isBusy || !isRunning}
      >
        <RefreshCw className="h-3.5 w-3.5" />
      </Button>

      <Button
        variant="ghost"
        size="icon"
        title="Console"
        onClick={() => navigate(`/containers/${container.name}/console`)}
        disabled={!isRunning}
      >
        <Terminal className="h-3.5 w-3.5" />
      </Button>

      <Button
        variant="ghost"
        size="icon"
        title="Delete"
        className="text-muted-foreground hover:text-destructive"
        onClick={() => {
          if (confirm(`Delete container "${container.name}"?`)) {
            deleteMut.mutate()
          }
        }}
        disabled={isBusy || isRunning}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>

      {isBusy && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const navigate = useNavigate()

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['containers'],
    queryFn: ({ signal }) => containers.list(signal),
    refetchInterval: 5000,
  })

  const stats = {
    total: data?.length ?? 0,
    running: data?.filter((c) => c.status === 'Running').length ?? 0,
    stopped: data?.filter((c) => c.status === 'Stopped').length ?? 0,
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground text-sm">Overview of your LXD containers</p>
        </div>
        <Button onClick={() => navigate('/containers/new')}>
          <Plus className="h-4 w-4" />
          New container
        </Button>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total', value: stats.total },
          { label: 'Running', value: stats.running },
          { label: 'Stopped', value: stats.stopped },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="rounded-lg border border-border bg-card p-4 flex flex-col gap-1"
          >
            <span className="text-xs text-muted-foreground font-medium">{label}</span>
            <span className="text-2xl font-bold">{value}</span>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="font-medium text-sm">Containers</h2>
          {isFetching && !isLoading && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          )}
        </div>

        {isLoading && (
          <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading containers…</span>
          </div>
        )}

        {isError && (
          <div className="flex items-center justify-center py-12 gap-2 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <span className="text-sm">{(error as Error).message}</span>
          </div>
        )}

        {!isLoading && !isError && data && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Name</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Status</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">IPv4</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Image</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Created</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-12 text-muted-foreground">
                      No containers found. Create one to get started.
                    </td>
                  </tr>
                )}
                {data.map((container) => (
                  <tr
                    key={container.name}
                    className={cn(
                      'border-b border-border last:border-0',
                      'hover:bg-muted/30 transition-colors',
                    )}
                  >
                    <td className="px-4 py-3">
                      <button
                        className="font-medium hover:text-primary transition-colors text-left"
                        onClick={() => navigate(`/containers/${container.name}`)}
                      >
                        {container.name}
                      </button>
                      {container.type === 'virtual-machine' && (
                        <span className="ml-2 text-xs text-muted-foreground">(VM)</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={statusVariant(container.status)}>
                        {container.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      {formatIpv4(container.ipv4)}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground max-w-[200px] truncate">
                      {container.image}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground text-xs whitespace-nowrap">
                      {formatRelativeTime(container.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <RowActions container={container} onMutate={() => {}} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
