import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertCircle, Database } from 'lucide-react'
import { storage as storageApi } from '@/lib/api'
import type { StoragePool } from '@/types/api'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatBytes } from '@/lib/utils'

function DriverBadge({ driver }: { driver: StoragePool['driver'] }) {
  return <Badge variant="outline">{driver}</Badge>
}

function UsageBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.round((used / total) * 100) : 0
  const color =
    pct >= 90
      ? 'bg-destructive'
      : pct >= 70
        ? 'bg-warning'
        : 'bg-success'

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{formatBytes(used)}</span>
        <span>{pct}%</span>
        <span>{formatBytes(total)}</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default function Storage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['storage'],
    queryFn: ({ signal }) => storageApi.list(signal),
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Storage</h1>
        <p className="text-muted-foreground text-sm">LXD storage pools and their utilisation.</p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading storage pools…</span>
        </div>
      )}

      {isError && (
        <div className="flex items-center justify-center py-12 gap-2 text-destructive">
          <AlertCircle className="h-5 w-5" />
          <span className="text-sm">{(error as Error).message}</span>
        </div>
      )}

      {!isLoading && !isError && data && data.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
          <Database className="h-10 w-10 opacity-30" />
          <p className="text-sm">No storage pools found.</p>
        </div>
      )}

      {!isLoading && !isError && data && data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((pool) => (
            <Card key={pool.name}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{pool.name}</CardTitle>
                  <div className="flex items-center gap-2">
                    <DriverBadge driver={pool.driver} />
                    <Badge
                      variant={
                        pool.status === 'Created'
                          ? 'success'
                          : pool.status === 'Errored'
                            ? 'destructive'
                            : 'secondary'
                      }
                    >
                      {pool.status}
                    </Badge>
                  </div>
                </div>
                {pool.description && (
                  <p className="text-xs text-muted-foreground mt-1">{pool.description}</p>
                )}
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Disk usage */}
                {pool.resources?.space && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-2">Disk usage</p>
                    <UsageBar
                      used={pool.resources.space.used}
                      total={pool.resources.space.total}
                    />
                  </div>
                )}

                {/* Inode usage */}
                {pool.resources?.inodes && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-2">Inode usage</p>
                    <UsageBar
                      used={pool.resources.inodes.used}
                      total={pool.resources.inodes.total}
                    />
                  </div>
                )}

                {/* Config */}
                {pool.config.source && (
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Source</span>
                    <span className="font-mono truncate max-w-[180px]">{pool.config.source}</span>
                  </div>
                )}

                {/* Used by */}
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Volumes / containers</span>
                  <span className="font-medium">{pool.used_by.length}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
