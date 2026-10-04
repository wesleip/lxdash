import { Link } from 'react-router-dom'
import { Server, TriangleAlert } from 'lucide-react'
import { useEffectiveHostId, useHosts } from '@/lib/hooks/useHosts'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'

/**
 * Read-only counterpart of the sidebar selector, for the top bar.
 *
 * In a multi-host panel "which daemon am I looking at?" has to be answerable
 * from every page, and the sidebar is collapsed on small screens. When the
 * choice is still missing it links to the flow that fixes it instead of
 * leaving the operator hunting for the selector.
 */
export function HostIndicator() {
  const { data: hosts } = useHosts()
  const activeHostId = useEffectiveHostId()
  const role = useAuthStore((s) => s.user?.role)

  // Still loading: render nothing rather than flash "no host".
  if (!hosts) return null

  const pill = 'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium'

  if (hosts.length === 0) {
    if (role !== 'admin') return null
    return (
      <Link
        to="/bootstrap"
        className={cn(pill, 'bg-destructive/10 text-destructive hover:bg-destructive/20')}
        title="No LXD host is registered yet"
      >
        <TriangleAlert className="h-3.5 w-3.5" />
        No LXD host registered
      </Link>
    )
  }

  const active = hosts.find((h) => h.id === activeHostId)

  if (!active) {
    return (
      <span
        className={cn(pill, 'bg-warning/10 text-warning')}
        title="Pick a host in the sidebar"
      >
        <TriangleAlert className="h-3.5 w-3.5" />
        Select a host
      </span>
    )
  }

  return (
    <span className={cn(pill, 'bg-muted text-muted-foreground')} title={active.address}>
      <Server className="h-3.5 w-3.5" />
      {active.name}
    </span>
  )
}