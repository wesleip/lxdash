import { useUiStore } from '@/store/ui'
import { useAuthStore } from '@/store/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Sun, Moon } from 'lucide-react'
import { cn } from '@/lib/utils'

type ThemeOption = 'dark' | 'light'

const THEME_OPTIONS: Array<{ value: ThemeOption; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
]

function ThemeCard() {
  const { theme, setTheme } = useUiStore()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Appearance</CardTitle>
        <CardDescription>Choose your preferred colour scheme.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex gap-3">
          {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              onClick={() => setTheme(value)}
              className={cn(
                'flex flex-col items-center gap-2 rounded-lg border-2 p-4 text-sm font-medium transition-colors',
                theme === value
                  ? 'border-primary bg-primary/5 text-primary'
                  : 'border-border hover:border-muted-foreground/40',
              )}
            >
              <Icon className="h-5 w-5" />
              {label}
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function AccountCard() {
  const { user, logout } = useAuthStore()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Account</CardTitle>
        <CardDescription>Your current session information.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {user ? (
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">{user.username}</p>
              <Badge variant="outline" className="mt-1 capitalize">
                {user.role}
              </Badge>
            </div>
            <Button variant="outline" size="sm" onClick={logout}>
              Sign out
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Not signed in.</p>
        )}
      </CardContent>
    </Card>
  )
}

function AboutCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">About LXDash</CardTitle>
        <CardDescription>Version information and links.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Version</span>
          <span className="font-mono">0.1.0</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Stack</span>
          <span>React 18 + FastAPI</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Query engine</span>
          <span>TanStack Query v5</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">LXD API</span>
          <span>1.0</span>
        </div>
      </CardContent>
    </Card>
  )
}

export default function Settings() {
  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground text-sm">Manage your preferences and account.</p>
      </div>

      <ThemeCard />
      <AccountCard />
      <AboutCard />
    </div>
  )
}
