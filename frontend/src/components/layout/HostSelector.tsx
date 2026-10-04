import { Link } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { useUiStore } from '@/store/ui'
import { useAuthStore } from '@/store/auth'
import { useEffectiveHostId, useActiveHosts } from '@/lib/hooks/useHosts'
import { cn } from '@/lib/utils'

interface HostSelectorProps {
  className?: string
}

/**
 * Picks the LXD host every resource page talks to.
 *
 * With a single registered host the choice is implicit ("Automatic"), which
 * keeps the common case one click-free. With several, the operator has to name
 * one — the backend rejects an ambiguous request with 422 rather than guessing.
 */
export function HostSelector({ className }: HostSelectorProps) {
  const hosts = useActiveHosts()
  const effectiveHostId = useEffectiveHostId()
  const { setActiveHostId } = useUiStore()
  const role = useAuthStore((s) => s.user?.role)

  if (hosts.length === 0) {
    const label = (
      <>
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">No host registered</span>
      </>
    )

    if (role === 'admin') {
      return (
        <Link
          to="/bootstrap"
          className={cn(
            'flex items-center gap-2 px-3 py-2 mx-2 mt-2 rounded-md',
            'bg-destructive/10 text-destructive text-xs font-medium',
            'hover:bg-destructive/20 transition-colors',
            className,
          )}
          title="No LXD host is registered yet"
        >
          {label}
        </Link>
      )
    }

    return (
      <div
        className={cn(
          'flex items-center gap-2 px-3 py-2 mx-2 mt-2 rounded-md',
          'bg-destructive/10 text-destructive text-xs font-medium',
          className,
        )}
        title="Ask an administrator to register an LXD host"
      >
        {label}
      </div>
    )
  }

  // A stale id (host removed in another tab, or persisted from an older
  // build) must degrade to "nothing selected" instead of leaving the <select>
  // pointing at an option that no longer exists. With a single host the
  // effective id is that host even while the store still says "Automatic", so
  // the select shows it instead of rendering blank.
  const selection = hosts.some((h) => h.id === effectiveHostId) ? effectiveHostId : null
  const needsExplicitChoice = hosts.length > 1 && selection === null

  return (
    <div className={cn('px-3 py-2 mx-2 mt-2', className)}>
      <label
        htmlFor="host-selector"
        className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1"
      >
        Host
      </label>
      <select
        id="host-selector"
        value={selection ?? ''}
        onChange={(e) =>
          setActiveHostId(e.target.value === '' ? null : Number(e.target.value))
        }
        className={cn(
          'w-full rounded-md border border-sidebar-border bg-sidebar-foreground/5',
          'px-2 py-1.5 text-xs font-medium text-sidebar-foreground',
          'focus:outline-none focus:ring-1 focus:ring-primary',
        )}
      >
        {needsExplicitChoice && (
          <option value="" disabled>
            Select a host…
          </option>
        )}
        {hosts.map((host) => (
          <option key={host.id} value={host.id}>
            {host.name}
          </option>
        ))}
      </select>
    </div>
  )
}