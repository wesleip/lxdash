import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Container,
  Image,
  Network,
  Database,
  Settings,
  LogOut,
  ChevronLeft,
  Server,
  Users,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUiStore } from '@/store/ui'
import { useAuthStore } from '@/store/auth'

interface NavItem {
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  end?: boolean
  adminOnly?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/containers', label: 'Containers', icon: Container },
  { to: '/images', label: 'Images', icon: Image },
  { to: '/networks', label: 'Networks', icon: Network },
  { to: '/storage', label: 'Storage', icon: Database },
  { to: '/users', label: 'Users', icon: Users, adminOnly: true },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar() {
  const { sidebarOpen, toggleSidebar, activeHostId } = useUiStore()
  const { user, logout } = useAuthStore()

  return (
    <aside
      className={cn(
        'flex flex-col h-full bg-sidebar border-r border-sidebar-border transition-all duration-200',
        sidebarOpen ? 'w-56' : 'w-14',
      )}
    >
      {/* Logo + collapse toggle */}
      <div
        className={cn(
          'flex items-center h-14 border-b border-sidebar-border shrink-0 px-3',
          sidebarOpen ? 'justify-between' : 'justify-center',
        )}
      >
        {sidebarOpen && (
          <div className="flex items-center gap-2 overflow-hidden">
            <Server className="h-5 w-5 text-primary shrink-0" />
            <span className="font-semibold text-sidebar-foreground truncate">LXDash</span>
          </div>
        )}
        <button
          onClick={toggleSidebar}
          className="rounded-md p-1 hover:bg-accent hover:text-accent-foreground transition-colors"
          aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          <ChevronLeft
            className={cn(
              'h-4 w-4 transition-transform',
              !sidebarOpen && 'rotate-180',
            )}
          />
        </button>
      </div>

      {/* Active host indicator */}
      {sidebarOpen && activeHostId && (
        <div className="px-3 py-2 mx-2 mt-2 rounded-md bg-primary/10 text-primary text-xs font-medium truncate">
          Host: {activeHostId}
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 py-2 overflow-y-auto">
        <ul className="space-y-0.5 px-2">
          {NAV_ITEMS.filter(({ adminOnly }) => !adminOnly || user?.role === 'admin').map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 px-2 py-2 rounded-md text-sm font-medium transition-colors',
                    'hover:bg-accent hover:text-accent-foreground',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-sidebar-foreground',
                    !sidebarOpen && 'justify-center',
                  )
                }
                title={!sidebarOpen ? label : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {sidebarOpen && <span>{label}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* User / Logout */}
      <div className="border-t border-sidebar-border p-2 shrink-0">
        {sidebarOpen && user && (
          <div className="px-2 py-1.5 mb-1">
            <p className="text-xs font-medium text-sidebar-foreground truncate">
              {user.username}
            </p>
            <p className="text-xs text-muted-foreground capitalize">{user.role}</p>
          </div>
        )}
        <button
          onClick={logout}
          className={cn(
            'flex w-full items-center gap-3 px-2 py-2 rounded-md text-sm font-medium',
            'text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors',
            !sidebarOpen && 'justify-center',
          )}
          title={!sidebarOpen ? 'Log out' : undefined}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {sidebarOpen && <span>Log out</span>}
        </button>
      </div>
    </aside>
  )
}
