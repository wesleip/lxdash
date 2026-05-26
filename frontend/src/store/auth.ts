import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types/api'

interface AuthState {
  token: string | null
  user: Pick<User, 'username' | 'role'> | null
  setAuth: (token: string, user: Pick<User, 'username' | 'role'>) => void
  logout: () => void
  isAuthenticated: () => boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,

      setAuth: (token, user) => {
        // Keep localStorage in sync so api.ts can read the token without
        // coupling directly to Zustand.
        localStorage.setItem('lxdash_token', token)
        set({ token, user })
      },

      logout: () => {
        localStorage.removeItem('lxdash_token')
        set({ token: null, user: null })
      },

      isAuthenticated: () => {
        return get().token !== null
      },
    }),
    {
      name: 'lxdash-auth',
      // Only persist the token; user info is re-fetched on mount.
      partialize: (state) => ({ token: state.token, user: state.user }),
    },
  ),
)
