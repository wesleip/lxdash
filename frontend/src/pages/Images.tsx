import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, AlertCircle, Trash2, RefreshCw } from 'lucide-react'
import { images as imagesApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { formatBytes, formatRelativeTime } from '@/lib/utils'

export default function Images() {
  const qc = useQueryClient()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['images'],
    queryFn: ({ signal }) => imagesApi.list(signal),
  })

  const deleteMut = useMutation({
    mutationFn: (fingerprint: string) => imagesApi.delete(fingerprint),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['images'] }),
  })

  const refreshMut = useMutation({
    mutationFn: (fingerprint: string) => imagesApi.refresh(fingerprint),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['images'] }),
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Images</h1>
        <p className="text-muted-foreground text-sm">
          Locally cached LXD images available for launching containers.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {isLoading && (
          <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading images…</span>
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
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Alias / Fingerprint</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">OS</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Release</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Architecture</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Type</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Size</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Uploaded</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-muted-foreground text-sm">
                      No cached images.
                    </td>
                  </tr>
                )}
                {data.map((image) => (
                  <tr
                    key={image.fingerprint}
                    className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      {image.alias ? (
                        <span className="font-medium">{image.alias}</span>
                      ) : (
                        <span className="font-mono text-xs text-muted-foreground">
                          {image.fingerprint.slice(0, 12)}…
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">{image.os}</td>
                    <td className="px-4 py-3">{image.release}</td>
                    <td className="px-4 py-3 text-muted-foreground">{image.architecture}</td>
                    <td className="px-4 py-3">
                      <Badge variant="outline">{image.type}</Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                      {formatBytes(image.size)}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground text-xs whitespace-nowrap">
                      {formatRelativeTime(image.upload_date)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Refresh image"
                          onClick={() => refreshMut.mutate(image.fingerprint)}
                          disabled={refreshMut.isPending}
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Delete image"
                          className="text-muted-foreground hover:text-destructive"
                          onClick={() => {
                            if (confirm(`Delete image ${image.alias ?? image.fingerprint.slice(0, 12)}?`)) {
                              deleteMut.mutate(image.fingerprint)
                            }
                          }}
                          disabled={deleteMut.isPending}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
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
