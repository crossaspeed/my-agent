import { App as AntApp, ConfigProvider, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { setUnauthorizedHandler } from '@/api/client'
import AppLayout from '@/components/AppLayout'
import ErrorBoundary from '@/components/ErrorBoundary'
import CoursesPage from '@/pages/Courses'
import ExamPage from '@/pages/Exam'
import LoginPage from '@/pages/Login'
import MyAttemptsPage from '@/pages/MyAttempts'
import ReportPage from '@/pages/Report'
import TutorPage from '@/pages/Tutor'
import CourseWorkbench from '@/pages/course/CourseWorkbench'
import { useAuth } from '@/store/auth'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 10_000 },
  },
})

function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAuth((s) => s.token)
  const ready = useAuth((s) => s.ready)
  if (!ready) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 160 }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function Bootstrapper() {
  const bootstrap = useAuth((s) => s.bootstrap)
  const logout = useAuth((s) => s.logout)
  const navigate = useNavigate()

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  useEffect(() => {
    // token 失效时统一跳转登录（拦截器触发）
    setUnauthorizedHandler(() => {
      logout()
      navigate('/login', { replace: true })
    })
  }, [logout, navigate])

  return null
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 8,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Bootstrapper />
            <ErrorBoundary>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route
                  element={
                    <RequireAuth>
                      <AppLayout />
                    </RequireAuth>
                  }
                >
                  <Route path="/courses" element={<CoursesPage />} />
                  <Route path="/courses/:courseId" element={<CourseWorkbench />} />
                  <Route path="/exam/:attemptId" element={<ExamPage />} />
                  <Route path="/report/:attemptId" element={<ReportPage />} />
                  <Route path="/attempts" element={<MyAttemptsPage />} />
                  <Route path="/tutor" element={<TutorPage />} />
                  <Route path="/tutor/:sessionId" element={<TutorPage />} />
                  <Route path="*" element={<Navigate to="/courses" replace />} />
                </Route>
              </Routes>
            </ErrorBoundary>
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
}
