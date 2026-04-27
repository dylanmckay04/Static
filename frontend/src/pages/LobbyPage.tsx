import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { createSeance, listSeances } from '../api/seances'
import type { SeanceResponse } from '../api/types'
import { sigilSvgHtml } from '../lib/sigil'
import { useAuth } from '../store/auth'

export default function LobbyPage() {
  const { token, clearToken } = useAuth()
  const navigate = useNavigate()

  const [seances,  setSeances]  = useState<SeanceResponse[]>([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState<string | null>(null)

  const [name,        setName]        = useState('')
  const [description, setDescription] = useState('')
  const [isSealed,    setIsSealed]    = useState(false)
  const [creating,    setCreating]    = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const fetchSeances = useCallback(async () => {
    if (!token) return
    try {
      setError(null)
      const data = await listSeances(token)
      setSeances(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { clearToken(); return }
      setError('The séances could not be summoned.')
    } finally {
      setLoading(false)
    }
  }, [token, clearToken])

  useEffect(() => { void fetchSeances() }, [fetchSeances])

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!token || !name.trim()) return
    setCreateError(null)
    setCreating(true)
    try {
      const s = await createSeance(
        { name: name.trim(), description: description.trim() || undefined, is_sealed: isSealed },
        token,
      )
      setName(''); setDescription(''); setIsSealed(false)
      setSeances(prev => [...prev, s])
      navigate(`/seances/${s.id}`)
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'The séance could not be opened.')
    } finally {
      setCreating(false)
    }
  }

  const enterSeance = (s: SeanceResponse) => {
    if (s.is_sealed) return
    navigate(`/seances/${s.id}`)
  }

  // Generate a small sigil icon for each seance name
  const nameSeal = (name: string) => ({ __html: sigilSvgHtml(name, 22) })

  return (
    <div className="lobby-layout">
      <header className="lobby-header">
        <h1 className="flicker">Veil</h1>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => void fetchSeances()}>
            Refresh
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => { clearToken(); navigate('/login') }}
          >
            Depart
          </button>
        </div>
      </header>

      <div className="lobby-body">
        {/* Create form */}
        <form className="create-form" onSubmit={handleCreate}>
          <h2>Open a new séance</h2>
          <div className="create-form-row">
            <input
              className="input"
              placeholder="Name this gathering"
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={100}
              required
              autoFocus
            />
            <input
              className="input"
              placeholder="Purpose or omen (optional)"
              value={description}
              onChange={e => setDescription(e.target.value)}
              maxLength={300}
            />
          </div>
          <div className="create-form-footer">
            <label>
              <input
                type="checkbox"
                checked={isSealed}
                onChange={e => setIsSealed(e.target.checked)}
              />
              Sealed — by invitation only
            </label>
            <button
              className="btn btn-primary btn-sm"
              type="submit"
              disabled={creating || !name.trim()}
            >
              {creating ? 'Opening the circle…' : 'Open séance'}
            </button>
            {createError && <span className="error-msg">{createError}</span>}
          </div>
        </form>

        {/* Séance list */}
        <div>
          <h2 style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16, textTransform: 'uppercase', letterSpacing: '0.12em' }}>
            Active séances
          </h2>

          {loading ? (
            <div className="center-page" style={{ padding: '48px 0' }}>
              <div className="spinner" />
              <span>Lighting the candles…</span>
            </div>
          ) : error ? (
            <p className="error-msg">{error}</p>
          ) : seances.length === 0 ? (
            <p className="empty-state">The board is silent. Open a séance above.</p>
          ) : (
            <div className="seance-grid">
              {seances.map(s => (
                <div
                  key={s.id}
                  className={`seance-card${s.is_sealed ? ' sealed' : ''}`}
                  onClick={() => enterSeance(s)}
                  role="button"
                  tabIndex={s.is_sealed ? -1 : 0}
                  onKeyDown={e => e.key === 'Enter' && enterSeance(s)}
                  title={s.is_sealed ? 'This séance is sealed' : undefined}
                >
                  <div className="seance-card-name">
                    <span dangerouslySetInnerHTML={nameSeal(s.name)} />
                    {s.name}
                    {s.is_sealed && <span className="badge badge-sealed">Sealed</span>}
                  </div>
                  {s.description && (
                    <div className="seance-card-desc">{s.description}</div>
                  )}
                  <div className="seance-card-footer">
                    <span className="badge badge-open">
                      {new Date(s.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
