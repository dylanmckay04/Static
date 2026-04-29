import { type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './store/auth'
import { ToastProvider } from './components/Toast'
import LoginPage    from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import LobbyPage    from './pages/LobbyPage'
import RoomPage     from './pages/RoomPage'
import InvitePage   from './pages/InvitePage'

function Protected({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/"            element={<Navigate to="/lobby" replace />} />
          <Route path="/login"       element={<LoginPage />} />
          <Route path="/register"    element={<RegisterPage />} />
          <Route path="/lobby"       element={<Protected><LobbyPage /></Protected>} />
          <Route path="/channels/:id" element={<Protected><RoomPage /></Protected>} />
          <Route path="/invite"      element={<InvitePage />} />
          <Route path="*"            element={<Navigate to="/lobby" replace />} />
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  )
}
