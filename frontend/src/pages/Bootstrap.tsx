import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, AlertCircle, CheckCircle2, Server, Plug } from 'lucide-react'
import { Link } from 'react-router-dom'
import { bootstrap as bootstrapApi } from '@/lib/api'
import { Button, buttonVariants } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { BootstrapResult } from '@/types/api'

// ---------------------------------------------------------------------------
// Status card — shown at the top, polls every 3s while in 'uninitialized'
// ---------------------------------------------------------------------------

function StatusBadge({ state }: { state: 'uninitialized' | 'untrusted' | 'initialized' }) {
  const map = {
    uninitialized: { label: 'Uninitialized', className: 'bg-warning/15 text-warning border-warning/30' },
    untrusted: { label: 'Untrusted', className: 'bg-destructive/15 text-destructive border-destructive/30' },
    initialized: { label: 'Initialized', className: 'bg-success/15 text-success border-success/30' },
  } as const
  const { label, className } = map[state]
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${className}`}>
      {label}
    </span>
  )
}

function StatusCard() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['bootstrap', 'status'],
    queryFn: ({ signal }) => bootstrapApi.status(signal),
    // Only poll while the daemon is uninitialized; once it's initialized the
    // status is stable and we don't need to keep hitting the backend.
    refetchInterval: (query) =>
      query.state.data?.state === 'uninitialized' ? 3000 : false,
  })

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Server className="h-4 w-4" />
          Local LXD daemon
        </CardTitle>
        <CardDescription>
          Detected state of the LXD daemon on this host.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Probing /1.0…
          </div>
        )}
        {isError && (
          <div className="flex items-start gap-2 text-destructive text-sm">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{(error as Error).message}</span>
          </div>
        )}
        {data && (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-3">
              <span className="text-muted-foreground">State</span>
              <StatusBadge state={data.state} />
            </div>
            {data.api_version && (
              <div className="flex items-center gap-3">
                <span className="text-muted-foreground">API</span>
                <span className="font-mono">{data.api_version}</span>
              </div>
            )}
            {data.server && (
              <div className="flex items-center gap-3">
                <span className="text-muted-foreground">Server</span>
                <span className="font-mono">{data.server}</span>
              </div>
            )}
            {data.socket && (
              <div className="flex items-center gap-3">
                <span className="text-muted-foreground">Socket</span>
                <span className="font-mono text-xs">{data.socket}</span>
              </div>
            )}
            {data.message && (
              <p className="text-muted-foreground text-xs pt-1">{data.message}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Bootstrap form — only rendered when state === 'uninitialized'
// ---------------------------------------------------------------------------

function BootstrapForm({ onSuccess }: { onSuccess: (result: BootstrapResult) => void }) {
  const [hostName, setHostName] = useState('')
  const [serverName, setServerName] = useState('')
  const [clusterPassword, setClusterPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mut = useMutation({
    mutationFn: () =>
      bootstrapApi.cluster({
        host_name: hostName.trim(),
        cluster: {
          server_name: serverName.trim(),
          cluster_password: clusterPassword,
        },
      }),
    onSuccess: (result) => onSuccess(result),
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!hostName.trim()) { setError('Host name is required.'); return }
    if (!serverName.trim()) { setError('Server name is required.'); return }
    if (clusterPassword.length < 12) {
      setError('Cluster password must be at least 12 characters.')
      return
    }
    mut.mutate()
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Plug className="h-4 w-4" />
          Bootstrap cluster
        </CardTitle>
        <CardDescription>
          Initialize the first node of an LXD cluster. The preseed is submitted
          via <code className="font-mono text-xs">POST /1.0/cluster</code> and a
          host record is created automatically so the rest of the app becomes
          usable immediately.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="bootstrap-host-name">Host name *</Label>
            <Input
              id="bootstrap-host-name"
              placeholder="node1"
              value={hostName}
              onChange={(e) => setHostName(e.target.value)}
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              Friendly name for the host record. Must be unique in the database.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="bootstrap-server-name">LXD server name *</Label>
            <Input
              id="bootstrap-server-name"
              placeholder="node1"
              value={serverName}
              onChange={(e) => setServerName(e.target.value)}
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              Cluster member name (1–63 chars). Must be unique within the cluster.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="bootstrap-password">Cluster password *</Label>
            <Input
              id="bootstrap-password"
              type="password"
              placeholder="Min. 12 characters"
              value={clusterPassword}
              onChange={(e) => setClusterPassword(e.target.value)}
              autoComplete="new-password"
            />
            <p className="text-xs text-muted-foreground">
              Shared secret used by other cluster members when joining.
            </p>
          </div>

          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}

          <div className="flex gap-2 pt-2">
            <Button type="submit" isLoading={mut.isPending}>
              Bootstrap cluster
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Result card — shown after a successful bootstrap
// ---------------------------------------------------------------------------

function SuccessCard({ result }: { result: BootstrapResult }) {
  return (
    <Card className="border-success/30">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base text-success">
          <CheckCircle2 className="h-4 w-4" />
          Cluster initialized
        </CardTitle>
        <CardDescription>
          The LXD cluster has been bootstrapped and the host is registered.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid grid-cols-[8rem_1fr] gap-y-2">
          <dt className="text-muted-foreground">Host ID</dt>
          <dd className="font-mono">#{result.host_id}</dd>
          <dt className="text-muted-foreground">Host name</dt>
          <dd className="font-medium">{result.host_name}</dd>
          <dt className="text-muted-foreground">Address</dt>
          <dd className="font-mono text-xs break-all">{result.address}</dd>
          <dt className="text-muted-foreground">Connection</dt>
          <dd>
            <span className="inline-flex items-center rounded-full border border-border bg-muted/50 px-2 py-0.5 text-xs font-medium">
              {result.connection_type}
            </span>
          </dd>
          <dt className="text-muted-foreground">Created at</dt>
          <dd className="text-xs">{new Date(result.created_at).toLocaleString()}</dd>
        </dl>
        <div className="pt-2">
          <Link to="/" className={cn(buttonVariants({ variant: 'default' }))}>
            Go to dashboard
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Untrusted / already-initialized info cards
// ---------------------------------------------------------------------------

function UntrustedCard() {
  return (
    <Card className="border-warning/30">
      <CardHeader className="pb-3">
        <CardTitle className="text-base text-warning">Cluster exists but client is not trusted</CardTitle>
        <CardDescription>
          An LXD cluster is already configured on this host, but our
          backend&apos;s client certificate has not been added to the trust store.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm space-y-2">
        <p>On the LXD host, run:</p>
        <pre className="rounded-md border border-border bg-muted/50 px-3 py-2 text-xs font-mono overflow-x-auto">
{`lxc config trust add /var/snap/lxd/common/lxd/unix.socket`}
        </pre>
        <p className="text-muted-foreground">
          After trusting the certificate, the dashboard will become usable.
          Adding additional cluster nodes remains an operator-driven step
          (<code className="font-mono text-xs">lxd cluster add</code>) until Phase 3.
        </p>
      </CardContent>
    </Card>
  )
}

function AlreadyInitializedCard({ hostName }: { hostName?: string }) {
  return (
    <Card className="border-success/30">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base text-success">
          <CheckCircle2 className="h-4 w-4" />
          Already initialized
        </CardTitle>
        <CardDescription>
          The LXD cluster on this host is already initialized
          {hostName && <> (<span className="font-mono">{hostName}</span>)</>}.
          Nothing to do here.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Link to="/" className={cn(buttonVariants({ variant: 'default' }))}>
          Go to dashboard
        </Link>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Bootstrap() {
  const qc = useQueryClient()
  const [result, setResult] = useState<BootstrapResult | null>(null)

  const status = useQuery({
    queryKey: ['bootstrap', 'status'],
    queryFn: ({ signal }) => bootstrapApi.status(signal),
    // Once a result lands, we don't need to keep polling.
    enabled: !result,
    refetchInterval: 3000,
  })

  // After a successful bootstrap, invalidate and re-fetch the status so the
  // page transitions from 'uninitialized' → 'initialized' cleanly.
  if (result) {
    void qc.invalidateQueries({ queryKey: ['bootstrap', 'status'] })
  }

  const state = status.data?.state

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Cluster setup</h1>
        <p className="text-muted-foreground text-sm">
          Initialize the first node of the LXD cluster that this LXDash instance will connect to.
        </p>
      </div>

      <StatusCard />

      {result ? (
        <SuccessCard result={result} />
      ) : state === 'uninitialized' ? (
        <BootstrapForm
          onSuccess={(r) => {
            setResult(r)
            void qc.invalidateQueries({ queryKey: ['bootstrap', 'status'] })
          }}
        />
      ) : state === 'untrusted' ? (
        <UntrustedCard />
      ) : state === 'initialized' ? (
        <AlreadyInitializedCard />
      ) : null}
    </div>
  )
}