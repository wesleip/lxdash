import { Outlet } from 'react-router-dom'
import { Sun, Moon, Menu } from 'lucide-react'
import { Sidebar } from './Sidebar'
import { useUiStore } from '@/store/ui'
import { cn } from '@/lib/utils'

export function AppLayout() {
  const { theme, toggleTheme, toggleSidebar } = useUiStore()

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center justify-between h-14 px-4 border-b border-border shrink-0 bg-background/80 backdrop-blur-sm">
          {/* Mobile sidebar toggle */}
          <button
            onClick={toggleSidebar}
            className="md:hidden rounded-md p-1.5 hover:bg-accent hover:text-accent-foreground"
            aria-label="Toggle sidebar"
          >
            <Menu className="h-5 w-5" />
          </button>

          <div className="flex-1" />

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            className="rounded-md p-1.5 hover:bg-accent hover:text-accent-foreground transition-colors"
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {theme === 'dark' ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </button>
        </header>

        {/* Page content */}
        <main
          className={cn(
            'flex-1 overflow-y-auto p-6',
            'focus:outline-none',
          )}
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}
