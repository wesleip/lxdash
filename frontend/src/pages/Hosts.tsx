import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Loader2, Plus, RefreshCw, Trash2, Server, Activity } from 'lucide-react'
import { hosts as hostsApi } from '@/lib/api'
import type { ConnectionType, HostCreate } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { LoadingState, ResourceError } from '@/components/common/ResourceState'
import { hostKeys, useHostHealth, useHosts } from '@/lib/hooks/useHosts'
import { useAuthStore } from '@/store/auth'
import { formatBytes, formatRelativeTime } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Health cell — one probe per host, polled independently
// ---------------------------------------------------------------------------

function HealthCell({ hostId, enabled }: { hostId: number; enabled: boolean }) {
  const { data, isLoading, isError } = useHostHealth(hostId, { enabled })

  if (!enabled) {
    return <span className="text-xs text-muted-foreground">skipped</span>
  }
  if (isLoading) {
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
  }
  if (isError || !data) {
    return <Badge variant="destructive">unreachable</Badge>
  }
  if (!data.reachable) {
    return (
      <Badge variant="destructive" title={data.message ?? undefined}>
        down
      </Badge>
    )
  }

  return (
    <div className="flex flex-col gap-0.5">
      <span className="flex items-center gap-1.5">
        <Badge variant="success">{data.clustered ? 'clustered' : 'standalone'}</Badge>
        <span className="font-mono text-xs text-muted-foreground">v{data.api_version}</span>
      </span>
      <span className="text-xs text-muted-foreground">
        {data.hostname ?? data.server_name ?? '—'}
        {data.cpu_total ? ` · ${data.cpu_total} vCPU` : ''}
        {data.memory_total ? ` · ${formatBytes(data.memory_total)} RAM` : ''}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Register form
// ---------------------------------------------------------------------------

const EMPTY_FORM: HostCreate = { name: '', address: '', connection_type: 'socket' }

function RegisterHostCard() {
  const qc = useQueryClient()
  const [form, setForm] = useState<HostCreate>(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)

  const mut = useMutation({
    mutationFn: () => hostsApi.create(form),
    onSuccess: () => {
      setForm(EMPTY_FORM)
      setError(null)
      void qc.invalidateQueries({ queryKey: hostKeys.list() })
    },
    onError: (err: Error) => setError(err.message),
  })

  const isTls = form.connection_type === 'tls'

  function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!form.name.trim()) {
      setError('Host name is required.')
      return
    }
    if (!form.address.trim()) {
      setError('Address is required.')
      return
    }
    mut.mutate()
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Plus className="h-4 w-4" />
          Register a host
        </CardTitle>
        <CardDescription>
          Adds a remote LXD daemon. The panel probes the LXD REST API before saving, so a
          wrong address or an untrusted certificate is rejected instead of stored.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="host-name">Name *</Label>
              <Input
                id="host-name"
                placeholder="node2"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                autoComplete="off"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="host-connection">Connection</Label>
              <select
                id="host-connection"
                value={form.connection_type ?? 'socket'}
                onChange={(e) =>
                  setForm({ ...form, connection_type: e.target.value as ConnectionType })
                }
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="socket">Unix socket</option>
                <option value="tls">TLS (remote)</option>
              </select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="host-address">Address *</Label>
            <Input
              id="host-address"
              placeholder={isTls ? 'https://10.0.0.1:8443' : '/var/snap/lxd/common/lxd/unix.socket'}
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              autoComplete="off"
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">
              {isTls
                ? 'The LXD HTTPS endpoint. Client certificate and key are required below.'
                : 'Absolute path of the LXD Unix socket on the machine running the backend.'}
            </p>
          </div>

          {isTls && (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="host-cert">Client certificate (PEM) *</Label>
                <textarea
                  id="host-cert"
                  rows={3}
                  value={form.tls_cert ?? ''}
                  onChange={(e) => setForm({ ...form, tls_cert: e.target.value })}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="host-key">Client private key (PEM) *</Label>
                <textarea
                  id="host-key"
                  rows={3}
                  value={form.tls_key ?? ''}
                  onChange={(e) => setForm({ ...form, tls_key: e.target.value })}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="host-server-cert">Server certificate to pin (PEM)</Label>
                <textarea
                  id="host-server-cert"
                  rows={3}
                  value={form.tls_server_cert ?? ''}
                  onChange={(e) => setForm({ ...form, tls_server_cert: e.target.value })}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                />
                <p className="text-xs text-muted-foreground">
                  Optional. Leave empty to skip verification, which is what LXD&apos;s self-signed
                  CA requires.
                </p>
              </div>
            </div>
          )}

          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}

          <Button type="submit" isLoading={mut.isPending}>
            Register host
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Hosts() {
  const qc = useQueryClient()
  const role = useAuthStore((s) => s.user?.role)
  const isAdmin = role === 'admin'

  const { data, isLoading, isError, error, isFetching, refetch } = useHosts()

  const removeMut = useMutation({
    mutationFn: (hostId: number) => hostsApi.remove(hostId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: hostKeys.list() }),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">LXD hosts</h1>
          <p className="text-muted-foreground text-sm">
            Every container, image, network and storage request is served by one of these daemons.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="shrink-0"
        >
          {isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          <span className="ml-1.5">Refresh</span>
        </Button>
      </div>

      {isLoading && <LoadingState label="Loading hosts…" />}
      {isError && <ResourceError error={error} />}

      {!isLoading && !isError && (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
            <Server className="h-4 w-4 text-muted-foreground" />
            <h2 className="font-medium text-sm">Registered</h2>
          </div>

          {(data?.length ?? 0) === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground space-y-3">
              <p>
                {isAdmin ? (
                  <>
                    No hosts registered yet.{' '}
                    <Link to="/bootstrap" className="text-primary hover:underline">
                      Register the local daemon
                    </Link>
                    , or add a remote one below.
                  </>
                ) : (
                  'No hosts registered yet. Ask an administrator to register one.'
                )}
              </p>
              {!isAdmin && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void refetch()}
                  disabled={isFetching}
                >
                  {isFetching ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  <span className="ml-1.5">Check again</span>
                </Button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Name</th>
                    <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">
                      Address
                    </th>
                    <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">
                      Health
                    </th>
                    <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">
                      Registered
                    </th>
                    {isAdmin && (
                      <th className="text-right px-4 py-2.5 font-medium text-muted-foreground">
                        Actions
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {data?.map((host) => (
                    <tr key={host.id} className="border-b border-border last:border-0">
                      <td className="px-4 py-3">
                        <span className="font-medium">{host.name}</span>
                        {!host.is_active && (
                          <Badge variant="secondary" className="ml-2">
                            inactive
                          </Badge>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-muted-foreground break-all">
                          {host.address}
                        </span>
                        <span className="ml-2 text-xs text-muted-foreground">
                          ({host.connection_type})
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <HealthCell hostId={host.id} enabled={host.is_active} />
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                        {formatRelativeTime(host.created_at)}
                      </td>
                      {isAdmin && (
                        <td className="px-4 py-3 text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            title="Remove host"
                            className="text-muted-foreground hover:text-destructive"
                            disabled={removeMut.isPending}
                            onClick={() => {
                              if (
                                confirm(
                                  `Remove host "${host.name}"? Containers and pools on the daemon are untouched.`,
                                )
                              ) {
                                removeMut.mutate(host.id)
                              }
                            }}
                          >
                            {removeMut.isPending ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                          </Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {!isLoading && isAdmin && (
        <>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Activity className="h-3.5 w-3.5" />
            Health is probed through the LXD REST API (<code className="font-mono">GET /1.0</code>)
            every 30 seconds.
          </p>
          <RegisterHostCard />
        </>
      )}
    </div>
  )
}