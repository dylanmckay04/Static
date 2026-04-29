import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { createChannel, listChannels } from '../api/channels'
import type { ChannelResponse } from '../api/types'
import { callsignSvgHtml } from '../lib/callsign'
import { useAuth } from '../store/auth'

export default function LobbyPage() {
  const { token, clearToken } = useAuth()
  const navigate = useNavigate()

  const [channels,  setChannels]  = useState<ChannelResponse[]>([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState<string | null>(null)

  const [name,        setName]        = useState('')
  const [description, setDescription] = useState('')
  const [isEncrypted,    setIsEncrypted]    = useState(false)
  const [creating,    setCreating]    = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const fetchChannels = useCallback(async () => {
    if (!token) return
    try {
      setError(null)
      const data = await listChannels(token)
      setChannels(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { clearToken(); return }
      setError('Could not retrieve channels.')
    } finally {
      setLoading(false)
    }
  }, [token, clearToken])

  useEffect(() => { void fetchChannels() }, [fetchChannels])

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!token || !name.trim()) return
    setCreateError(null)
    setCreating(true)
    try {
      const s = await createChannel(
        { name: name.trim(), description: description.trim() || undefined, is_encrypted: isEncrypted },
        token,
      )
      setName(''); setDescription(''); setIsEncrypted(false)
      setChannels(prev => [...prev, s])
      navigate(`/channels/${s.id}`)
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'The channel could not be opened.')
    } finally {
      setCreating(false)
    }
  }

  const enterChannel = (s: ChannelResponse) => {
    navigate(`/channels/${s.id}`)
  }

  // Generate a small callsign icon for each channel name
  const nameCallsign = (name: string) => ({ __html: callsignSvgHtml(name, 22) })

  return (
    <div className="lobby-layout">
      <header className="lobby-header">
        <h1 className="scanline">Static</h1>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => void fetchChannels()}>
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
          <h2>Open a new channel</h2>
          <div className="create-form-row">
            <input
              className="input"
              placeholder="Channel name"
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={100}
              required
              autoFocus
            />
            <input
              className="input"
              placeholder="Purpose (optional)"
              value={description}
              onChange={e => setDescription(e.target.value)}
              maxLength={300}
            />
          </div>
          <div className="create-form-footer">
            <label>
              <input
                type="checkbox"
                checked={isEncrypted}
                onChange={e => setIsEncrypted(e.target.checked)}
              />
              Encrypted — cipher key required
            </label>
            <button
              className="btn btn-primary btn-sm"
              type="submit"
              disabled={creating || !name.trim()}
            >
              {creating ? 'Opening channel…' : 'Open channel'}
            </button>
            {createError && <span className="error-msg">{createError}</span>}
          </div>
        </form>

        {/* Séance list */}
        <div>
          <h2 style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16, textTransform: 'uppercase', letterSpacing: '0.12em' }}>
            Active channels
          </h2>

          {loading ? (
            <div className="center-page" style={{ padding: '48px 0' }}>
              <div className="spinner" />
              <span>Scanning frequencies…</span>
            </div>
          ) : error ? (
            <p className="error-msg">{error}</p>
          ) : channels.length === 0 ? (
            <p className="empty-state">No channels found. Open one above.</p>
          ) : (
            <div className="channel-grid">
              {channels.map(s => (
                <div
                  key={s.id}
                  className={`channel-card${s.is_encrypted ? ' sealed' : ''}`}
                  onClick={() => enterChannel(s)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={e => e.key === 'Enter' && enterChannel(s)}
                  title={s.is_encrypted ? 'This channel is encrypted — cipher key required' : undefined}
                >
                  <div className="channel-card-name">
                    <span dangerouslySetInnerHTML={nameCallsign(s.name)} />
                    {s.name}
                    {s.is_encrypted && <span className="badge badge-encrypted">Encrypted</span>}
                  </div>
                  {s.description && (
                    <div className="channel-card-desc">{s.description}</div>
                  )}
                  <div className="channel-card-footer">
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
