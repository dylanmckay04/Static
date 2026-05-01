import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getGithubLoginUrl, getGoogleLoginUrl, login } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../store/auth'

export default function LoginPage() {
  const { setToken } = useAuth()
  const navigate = useNavigate()
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState<string | null>(null)
  const [loading,  setLoading]  = useState(false)
  const [ghLoading, setGhLoading] = useState(false)
  const [gLoading,  setGLoading]  = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { access_token } = await login({ email, password })
      setToken(access_token)
      const pending = sessionStorage.getItem('pendingCipherKey')
      if (pending) {
        sessionStorage.removeItem('pendingCipherKey')
        navigate(`/invite?token=${encodeURIComponent(pending)}`, { replace: true })
      } else {
        navigate('/lobby', { replace: true })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Access denied. Check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  const handleGithubLogin = async () => {
    setError(null)
    setGhLoading(true)
    try {
      const { url } = await getGithubLoginUrl()
      window.location.href = url
    } catch {
      setError('Could not reach GitHub. Try again.')
      setGhLoading(false)
    }
  }

  const handleGoogleLogin = async () => {
    setError(null)
    setGLoading(true)
    try {
      const { url } = await getGoogleLoginUrl()
      window.location.href = url
    } catch {
      setError('Could not reach Google. Try again.')
      setGLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title scanline">Static</h1>
        <p className="auth-subtitle">Tune in to the frequency</p>
        <form onSubmit={handleSubmit} className="auth-form">
          <input
            className="input" type="email" placeholder="Your address"
            value={email} onChange={e => setEmail(e.target.value)}
            required autoFocus
          />
          <input
            className="input" type="password" placeholder="Passphrase"
            value={password} onChange={e => setPassword(e.target.value)}
            required
          />
          {error && <p className="error-msg">{error}</p>}
          <button className="btn btn-primary" type="submit" disabled={loading || ghLoading || gLoading}>
            {loading ? 'Authenticating…' : 'Enter'}
          </button>
        </form>
        <div className="auth-divider">— or —</div>
        <button
          type="button"
          className="btn btn-ghost"
          style={{ width: '100%' }}
          onClick={handleGoogleLogin}
          disabled={gLoading || ghLoading || loading}
        >
          {gLoading ? 'Redirecting…' : 'Sign in with Google'}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          style={{ width: '100%' }}
          onClick={handleGithubLogin}
          disabled={ghLoading || gLoading || loading}
        >
          {ghLoading ? 'Redirecting…' : 'Sign in with GitHub'}
        </button>
        <p className="auth-link">
          No account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  )
}
