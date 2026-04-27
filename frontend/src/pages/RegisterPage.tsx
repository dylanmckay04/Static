import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login, register } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../store/auth'

export default function RegisterPage() {
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
      await register({ email, password })
      const { access_token } = await login({ email, password })
      setToken(access_token)
      navigate('/lobby', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The ritual failed. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title flicker">Veil</h1>
        <p className="auth-subtitle">Inscribe your name in the book</p>
        <form onSubmit={handleSubmit} className="auth-form">
          <input
            className="input" type="email" placeholder="Your address"
            value={email} onChange={e => setEmail(e.target.value)}
            required autoFocus
          />
          <input
            className="input" type="password" placeholder="Passphrase (8 characters or more)"
            value={password} onChange={e => setPassword(e.target.value)}
            required minLength={8}
          />
          {error && <p className="error-msg">{error}</p>}
          <button className="btn btn-primary" type="submit" disabled={loading}>
            {loading ? 'Inscribing…' : 'Bind my name'}
          </button>
        </form>
        <p className="auth-link">
          Already bound? <Link to="/login">Enter</Link>
        </p>
      </div>
    </div>
  )
}
