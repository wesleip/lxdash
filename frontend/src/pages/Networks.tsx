import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, AlertCircle, Trash2, Plus, ChevronDown } from 'lucide-react'
import { networks as networksApi } from '@/lib/api'
import type { CreateNetworkRequest, NetworkType } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const NETWORK_TYPES: NetworkType[] = ['bridge', 'macvlan', 'physical', 'ovn']

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === 'Created'
      ? 'success'
      : status === 'Errored'
        ? 'destructive'
        : 'secondary'
  return <Badge variant={variant}>{status}</Badge>
}

export default function Networks() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<CreateNetworkRequest>({
    name: '',
    description: '',
    type: 'bridge',
    config: {
      'ipv4.address': '10.0.0.1/24',
      'ipv4.nat': 'true',
      'ipv6.address': 'none',
    },
  })
  const [formError, setFormError] = useState<string | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['networks'],
    queryFn: ({ signal }) => networksApi.list(signal),
  })

  const createMut = useMutation({
    mutationFn: () => networksApi.create(form),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['networks'] })
      setShowCreate(false)
      setForm({ name: '', description: '', type: 'bridge', config: {} })
      setFormError(null)
    },
    onError: (err: Error) => setFormError(err.message),
  })

  const deleteMut = useMutation({
    mutationFn: (name: string) => networksApi.delete(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['networks'] }),
  })

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.name.trim()) {
      setFormError('Network name is required.')
      return
    }
    createMut.mutate()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Networks</h1>
          <p className="text-muted-foreground text-sm">Managed LXD networks and bridges.</p>
        </div>
        <Button onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? (
            <>
              <ChevronDown className="h-4 w-4" />
              Cancel
            </>
          ) : (
            <>
              <Plus className="h-4 w-4" />
              New network
            </>
          )}
        </Button>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Create network</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="net-name">Name *</Label>
                  <Input
                    id="net-name"
                    placeholder="lxdbr1"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="net-type">Type</Label>
                  <select
                    id="net-type"
                    value={form.type}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, type: e.target.value as NetworkType }))
                    }
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {NETWORK_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="net-ipv4">IPv4 address (CIDR)</Label>
                  <Input
                    id="net-ipv4"
                    placeholder="10.0.0.1/24"
                    value={form.config?.['ipv4.address'] ?? ''}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        config: { ...f.config, 'ipv4.address': e.target.value },
                      }))
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="net-ipv6">IPv6 address (CIDR or "none")</Label>
                  <Input
                    id="net-ipv6"
                    placeholder="none"
                    value={form.config?.['ipv6.address'] ?? ''}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        config: { ...f.config, 'ipv6.address': e.target.value },
                      }))
                    }
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="net-desc">Description</Label>
                  <Input
                    id="net-desc"
                    placeholder="Optional description"
                    value={form.description ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </div>
              </div>

              {formError && (
                <p className="text-sm text-destructive" role="alert">
                  {formError}
                </p>
              )}

              <div className="flex gap-2">
                <Button type="submit" isLoading={createMut.isPending}>
                  Create
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowCreate(false)}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Networks table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {isLoading && (
          <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading networks…</span>
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
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Type</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Status</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">IPv4</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">IPv6</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Managed</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Used by</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-muted-foreground text-sm">
                      No networks found.
                    </td>
                  </tr>
                )}
                {data.map((network) => (
                  <tr
                    key={network.name}
                    className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium">{network.name}</td>
                    <td className="px-4 py-3">
                      <Badge variant="outline">{network.type}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={network.status} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      {network.config['ipv4.address'] ?? '—'}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      {network.config['ipv6.address'] ?? '—'}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={network.managed ? 'success' : 'secondary'}>
                        {network.managed ? 'Yes' : 'No'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground text-xs">
                      {network.used_by.length > 0 ? network.used_by.length : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <Button
                        variant="ghost"
                        size="icon"
                        title="Delete network"
                        className="text-muted-foreground hover:text-destructive"
                        disabled={!network.managed || network.used_by.length > 0 || deleteMut.isPending}
                        onClick={() => {
                          if (confirm(`Delete network "${network.name}"?`)) {
                            deleteMut.mutate(network.name)
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
          </div>
        )}
      </div>
    </div>
  )
}
