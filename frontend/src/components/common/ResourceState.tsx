import { Link } from 'react-router-dom'
import { AlertCircle, Loader2, ServerCrash, ServerCog } from 'lucide-react'
import { ApiError } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'

interface ResourceStateProps {
  className?: string
  /** Shown above the message so a page can explain what failed. */
  label?: string
}

function Shell({
  icon,
  title,
  children,
  className,
}: {
  icon: React.ReactNode
  title: string
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 py-12 px-6 text-center',
        className,
      )}
    >
      <div className="text-muted-foreground">{icon}</div>
      <p className="text-sm font-medium">{title}</p>
      {children}
    </div>
  )
}

export function LoadingState({ label = 'Loading…', className }: ResourceStateProps) {
  return (
    <Shell icon={<Loader2 className="h-5 w-5 animate-spin" />} title={label} className={className} />
  )
}

/**
 * Explains why a resource query failed, in terms the operator can act on.
 *
 * The 409 case is the one that used to be a dead end: the backend refuses to
 * serve any LXD resource without a `hosts` row, so the fix is always the same —
 * register a host — and the panel has to offer that route instead of only
 * printing the status text.
 */
export function ResourceError({ error, className }: { error: unknown; className?: string }) {
  const user = useAuthStore((s) => s.user)
  const status = error instanceof ApiError ? error.status : undefined
  const detail = error instanceof Error ? error.message : String(error)

  if (status === 409) {
    return (
      <Shell icon={<ServerCog className="h-5 w-5" />} title="No LXD host is registered" className={className}>
        <p className="text-sm text-muted-foreground max-w-md">
          Every container, image, network and storage request is served by a registered LXD
          host. Register the local daemon to continue.
        </p>
        {user?.role === 'admin' ? (
          <Link
            to="/bootstrap"
            className="mt-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity"
          >
            Register a host
          </Link>
        ) : (
          <p className="text-sm text-muted-foreground">Ask an administrator to register one.</p>
        )}
      </Shell>
    )
  }

  if (status === 422) {
    return (
      <Shell
        icon={<ServerCog className="h-5 w-5" />}
        title="Several hosts are registered"
        className={className}
      >
        <p className="text-sm text-muted-foreground max-w-md">{detail}</p>
        <p className="text-sm text-muted-foreground">Pick a host in the sidebar.</p>
      </Shell>
    )
  }

  if (status === 502) {
    return (
      <Shell
        icon={<ServerCrash className="h-5 w-5" />}
        title="The LXD host is unreachable"
        className={className}
      >
        <p className="text-sm text-muted-foreground max-w-md">{detail}</p>
      </Shell>
    )
  }

  return (
    <Shell icon={<AlertCircle className="h-5 w-5 text-destructive" />} title={detail} className={className} />
  )
}