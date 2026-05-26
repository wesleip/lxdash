import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'

import { AppLayout } from '@/components/layout/AppLayout'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'

// Lazy-load pages so the initial bundle stays small.
const LoginPage = lazy(() => import('@/pages/LoginPage'))
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const ContainerDetail = lazy(() => import('@/pages/ContainerDetail'))
const Terminal = lazy(() => import('@/pages/Terminal'))
const Images = lazy(() => import('@/pages/Images'))
const Networks = lazy(() => import('@/pages/Networks'))
const Storage = lazy(() => import('@/pages/Storage'))
const Settings = lazy(() => import('@/pages/Settings'))

function PageSpinner() {
  return (
    <div className="flex h-full min-h-[200px] items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  )
}

export default function App() {
  return (
    <Suspense fallback={<PageSpinner />}>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />

        {/* Protected routes — all wrapped in AppLayout */}
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            {/* Dashboard at root */}
            <Route index element={<Dashboard />} />

            {/* Container routes */}
            <Route path="containers">
              {/* /containers redirects to dashboard (list is on the dashboard) */}
              <Route index element={<Navigate to="/" replace />} />
              <Route path=":name" element={<ContainerDetail />} />
              {/* Console uses full-screen layout, still protected */}
            </Route>

            {/* Other sections */}
            <Route path="images" element={<Images />} />
            <Route path="networks" element={<Networks />} />
            <Route path="storage" element={<Storage />} />
            <Route path="settings" element={<Settings />} />
          </Route>

          {/* Console is outside AppLayout (full-screen terminal) */}
          <Route
            path="containers/:name/console"
            element={
              <div className="flex h-screen flex-col bg-[#0d1117]">
                <Suspense fallback={<PageSpinner />}>
                  <Terminal />
                </Suspense>
              </div>
            }
          />
        </Route>

        {/* Catch-all: redirect unknown paths to root */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
