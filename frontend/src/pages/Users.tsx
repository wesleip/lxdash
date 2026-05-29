import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Loader2,
  AlertCircle,
  Plus,
  ChevronDown,
  Pencil,
  Trash2,
  KeyRound,
  ShieldCheck,
  Eye,
  Wrench,
} from 'lucide-react'
import { users as usersApi } from '@/lib/api'
import type { User, UserRole } from '@/types/api'
import { useAuthStore } from '@/store/auth'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

const ROLES: UserRole[] = ['admin', 'operator', 'viewer']

const ROLE_META: Record<UserRole, { label: string; icon: React.ComponentType<{ className?: string }>; variant: 'destructive' | 'default' | 'secondary' }> = {
  admin: { label: 'Admin', icon: ShieldCheck, variant: 'destructive' },
  operator: { label: 'Operator', icon: Wrench, variant: 'default' },
  viewer: { label: 'Viewer', icon: Eye, variant: 'secondary' },
}

function RoleBadge({ role }: { role: UserRole }) {
  const { label, icon: Icon, variant } = ROLE_META[role]
  return (
    <Badge variant={variant} className="gap-1">
      <Icon className="h-3 w-3" />
      {label}
    </Badge>
  )
}

function UserAvatar({ username }: { username: string }) {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-semibold">
      {username.slice(0, 2).toUpperCase()}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Create form (inline card)
// ---------------------------------------------------------------------------

function CreateForm({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ username: '', email: '', password: '', role: 'viewer' as UserRole })
  const [error, setError] = useState<string | null>(null)

  const mut = useMutation({
    mutationFn: () => usersApi.create(form),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['users'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!form.username.trim()) { setError('Username is required.'); return }
    if (!form.email.trim()) { setError('Email is required.'); return }
    if (form.password.length < 8) { setError('Password must be at least 8 characters.'); return }
    mut.mutate()
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Create user</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="u-username">Username *</Label>
              <Input
                id="u-username"
                placeholder="jdoe"
                value={form.username}
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="u-email">Email *</Label>
              <Input
                id="u-email"
                type="email"
                placeholder="jdoe@example.com"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="u-password">Password *</Label>
              <Input
                id="u-password"
                type="password"
                placeholder="Min. 8 characters"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="u-role">Role</Label>
              <select
                id="u-role"
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as UserRole }))}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>{ROLE_META[r].label}</option>
                ))}
              </select>
            </div>
          </div>

          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}

          <div className="flex gap-2">
            <Button type="submit" isLoading={mut.isPending}>Create</Button>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Edit dialog (inline row expansion)
// ---------------------------------------------------------------------------

function EditRow({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient()
  const [role, setRole] = useState<UserRole>(user.role)
  const [isActive, setIsActive] = useState(user.is_active)
  const [error, setError] = useState<string | null>(null)

  const mut = useMutation({
    mutationFn: () => usersApi.update(user.id, { role, is_active: isActive }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['users'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  return (
    <tr className="bg-muted/20 border-b border-border">
      <td colSpan={6} className="px-4 py-3">
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1.5">
            <Label htmlFor={`edit-role-${user.id}`}>Role</Label>
            <select
              id={`edit-role-${user.id}`}
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
              className="flex h-9 rounded-md border border-input bg-background px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{ROLE_META[r].label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2 pb-1">
            <input
              id={`edit-active-${user.id}`}
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <Label htmlFor={`edit-active-${user.id}`} className="cursor-pointer">Active</Label>
          </div>
          {error && <p className="text-sm text-destructive pb-1">{error}</p>}
          <div className="flex gap-2 pb-1">
            <Button size="sm" isLoading={mut.isPending} onClick={() => mut.mutate()}>Save</Button>
            <Button size="sm" variant="outline" onClick={onClose}>Cancel</Button>
          </div>
        </div>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Reset password dialog (inline row expansion)
// ---------------------------------------------------------------------------

function ResetPasswordRow({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mut = useMutation({
    mutationFn: () => usersApi.resetPassword(user.id, password),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['users'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    mut.mutate()
  }

  return (
    <tr className="bg-muted/20 border-b border-border">
      <td colSpan={6} className="px-4 py-3">
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-4">
          <div className="space-y-1.5">
            <Label htmlFor={`pwd-${user.id}`}>New password for <span className="font-semibold">{user.username}</span></Label>
            <Input
              id={`pwd-${user.id}`}
              type="password"
              placeholder="Min. 8 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-64"
            />
          </div>
          {error && <p className="text-sm text-destructive pb-1">{error}</p>}
          <div className="flex gap-2 pb-1">
            <Button type="submit" size="sm" isLoading={mut.isPending}>Reset</Button>
            <Button type="button" size="sm" variant="outline" onClick={onClose}>Cancel</Button>
          </div>
        </form>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type ExpandedRow = { id: number; mode: 'edit' | 'reset-password' } | null

export default function Users() {
  const qc = useQueryClient()
  const currentUser = useAuthStore((s) => s.user)
  const [showCreate, setShowCreate] = useState(false)
  const [expanded, setExpanded] = useState<ExpandedRow>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['users'],
    queryFn: ({ signal }) => usersApi.list(signal),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => usersApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  function toggle(id: number, mode: 'edit' | 'reset-password') {
    setExpanded((prev) =>
      prev?.id === id && prev.mode === mode ? null : { id, mode },
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Users</h1>
          <p className="text-muted-foreground text-sm">Manage accounts and roles.</p>
        </div>
        <Button onClick={() => { setShowCreate((v) => !v); setExpanded(null) }}>
          {showCreate ? (
            <><ChevronDown className="h-4 w-4" />Cancel</>
          ) : (
            <><Plus className="h-4 w-4" />New user</>
          )}
        </Button>
      </div>

      {showCreate && <CreateForm onClose={() => setShowCreate(false)} />}

      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {isLoading && (
          <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading users…</span>
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
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">User</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Email</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Role</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Status</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Created</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-12 text-muted-foreground text-sm">
                      No users found.
                    </td>
                  </tr>
                )}
                {data.map((user) => {
                  const isSelf = user.username === currentUser?.username
                  const isExpanded = expanded?.id === user.id

                  return [
                    <tr
                      key={user.id}
                      className={cn(
                        'border-b border-border last:border-0 hover:bg-muted/30 transition-colors',
                        isExpanded && 'bg-muted/20',
                      )}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <UserAvatar username={user.username} />
                          <span className="font-medium">
                            {user.username}
                            {isSelf && <span className="ml-1.5 text-xs text-muted-foreground">(you)</span>}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{user.email ?? '—'}</td>
                      <td className="px-4 py-3"><RoleBadge role={user.role} /></td>
                      <td className="px-4 py-3">
                        <Badge variant={user.is_active ? 'success' : 'secondary'}>
                          {user.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">
                        {new Date(user.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            title="Edit role / status"
                            className={cn(
                              'text-muted-foreground hover:text-foreground',
                              expanded?.id === user.id && expanded.mode === 'edit' && 'text-primary',
                            )}
                            onClick={() => toggle(user.id, 'edit')}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            title="Reset password"
                            className={cn(
                              'text-muted-foreground hover:text-foreground',
                              expanded?.id === user.id && expanded.mode === 'reset-password' && 'text-primary',
                            )}
                            onClick={() => toggle(user.id, 'reset-password')}
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            title="Delete user"
                            className="text-muted-foreground hover:text-destructive"
                            disabled={isSelf || deleteMut.isPending}
                            onClick={() => {
                              if (confirm(`Delete user "${user.username}"? This action cannot be undone.`)) {
                                deleteMut.mutate(user.id)
                              }
                            }}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>,
                    expanded?.id === user.id && expanded.mode === 'edit' && (
                      <EditRow key={`edit-${user.id}`} user={user} onClose={() => setExpanded(null)} />
                    ),
                    expanded?.id === user.id && expanded.mode === 'reset-password' && (
                      <ResetPasswordRow key={`pwd-${user.id}`} user={user} onClose={() => setExpanded(null)} />
                    ),
                  ]
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
