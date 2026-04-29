import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../store/auth'

export default function LoginPage() {
  const { setToken } = useAuth()
  const navigate = useNavigate()
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState<string | null>(null)
  const [loading,  setLoading]  = useState(false)

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
          <button className="btn btn-primary" type="submit" disabled={loading}>
            {loading ? 'Authenticating…' : 'Enter'}
          </button>
        </form>
        <p className="auth-link">
          No account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  )
}
