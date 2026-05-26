import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/store/auth'

interface ProtectedRouteProps {
  /** Redirect target when unauthenticated. Defaults to /login */
  redirectTo?: string
}

/**
 * Wraps routes that require authentication.
 * Saves the current location so LoginPage can redirect back after login.
 */
export function ProtectedRoute({ redirectTo = '/login' }: ProtectedRouteProps) {
  const token = useAuthStore((s) => s.token)
  const location = useLocation()

  if (!token) {
    return (
      <Navigate
        to={redirectTo}
        state={{ from: location }}
        replace
      />
    )
  }

  return <Outlet />
}
