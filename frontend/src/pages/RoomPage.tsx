import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  createCipherKey,
  departChannel,
  dissolveChannel,
  enterChannel,
  getChannel,
  getMyContact,
  getTransmissions,
  kickByCallsign,
  listContacts,
  redactTransmission,
  setRoleByCallsign,
  transferControllerByCallsign,
} from '../api/channels'
import type { OwnContactResponse, ContactResponse, ContactRole, TransmissionResponse, WsMessage } from '../api/types'
import { callsignSvgHtml } from '../lib/callsign'
import {
  playConnectionDrop,
  playTransmissionSent,
  playReconnected,
  playTransmissionReceived,
  setEnabled as setSoundEnabled,
} from '../lib/sounds'
import { useToast } from '../components/Toast'
import { useChannelSocket } from '../lib/useChannelSocket'
import { useAuth } from '../store/auth'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === now.toDateString()) return timeStr
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + timeStr
}

function mergeTransmissions(a: TransmissionResponse[], b: TransmissionResponse[]): TransmissionResponse[] {
  const map = new Map<number, TransmissionResponse>()
  for (const w of [...a, ...b]) map.set(w.id, w)
  return Array.from(map.values()).sort((x, y) => x.id - y.id)
}

function CallsignSeal({ callsign, size = 28 }: { callsign: string; size?: number }) {
  return (
    <span
      className="contact-callsign-seal"
      dangerouslySetInnerHTML={{ __html: callsignSvgHtml(callsign, size) }}
    />
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

type PageStatus = 'loading' | 'ready' | 'error'

export default function RoomPage() {
  const { id }      = useParams<{ id: string }>()
  const channelId    = Number(id)
  const { token, clearToken } = useAuth()
  const navigate    = useNavigate()
  const toast       = useToast()

  const [status,      setStatus]      = useState<PageStatus>('loading')
  const [pageError,   setPageError]   = useState<string | null>(null)
  const [channelName,  setChannelName]  = useState('')
  const [myContact,   setMyContact]   = useState<OwnContactResponse | null>(null)
  const [contacts,    setContacts]    = useState<ContactResponse[]>([])
  const [transmissions,    setTransmissions]    = useState<TransmissionResponse[]>([])
  const [nextBefore,  setNextBefore]  = useState<number | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [draft,       setDraft]       = useState('')
  const [wsReady,     setWsReady]     = useState(false)
  const [soundOn,     setSoundOn]     = useState(false)
  const [copying,     setCopying]     = useState(false)

  const bottomRef    = useRef<HTMLDivElement>(null)
  const textareaRef  = useRef<HTMLTextAreaElement>(null)
  const mountedRef   = useRef(true)
  const prevWsStatus = useRef<string>('')

  useEffect(() => { return () => { mountedRef.current = false } }, [])

  // ── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!token) return
    let cancelled = false

    const init = async () => {
      try {
        let own: OwnContactResponse
        try {
          own = await enterChannel(channelId, token)
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            own = await getMyContact(channelId, token)
          } else if (err instanceof ApiError && err.status === 401) {
            clearToken(); return
          } else {
            throw err
          }
        }
        if (cancelled) return
        setMyContact(own)

        const [channel, contactList] = await Promise.all([
          getChannel(channelId, token),
          listContacts(channelId, token),
        ])
        if (!cancelled) setChannelName(channel.name)
        if (cancelled) return
        setContacts(contactList)

        const page = await getTransmissions(channelId, { limit: 50 }, token)
        if (cancelled) return
        setTransmissions([...page.items].reverse())
        setNextBefore(page.next_before_id)

        setStatus('ready')
        setWsReady(true)
      } catch (err) {
        if (!cancelled) {
          setPageError(err instanceof ApiError ? err.message : 'The channel could not be entered.')
          setStatus('error')
        }
      }
    }

    void init()
    return () => { cancelled = true }
  }, [channelId, token, clearToken])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transmissions.length])

  // ── WS message handler ────────────────────────────────────────────────────

  const handleWsMessage = useCallback((msg: WsMessage) => {
    switch (msg.op) {
      case 'transmission': {
        const w: TransmissionResponse = {
          id: msg.id, channel_id: msg.channel_id,
          callsign: msg.callsign, content: msg.content,
          is_deleted: msg.is_deleted ?? false,
          created_at: msg.created_at,
        }
        setTransmissions(prev => mergeTransmissions(prev, [w]))
        setMyContact(me => {
          if (me && msg.callsign !== me.callsign) playTransmissionReceived()
          return me
        })
        break
      }
      case 'enter':
        setContacts(prev => {
          if (prev.some(p => p.callsign === msg.callsign)) return prev
          return [...prev, { callsign: msg.callsign, role: 'listener', entered_at: new Date().toISOString() }]
        })
        break
      case 'depart':
        setContacts(prev => prev.filter(p => p.callsign !== msg.callsign))
        break
      case 'redact':
        setTransmissions(prev => prev.map(w =>
          w.id === msg.transmission_id
            ? { ...w, is_deleted: true, content: '⸻ redacted ⸻' }
            : w
        ))
        break
      case 'promote':
        setContacts(prev => prev.map(p =>
          p.callsign === msg.callsign ? { ...p, role: msg.role } : p
        ))
        setMyContact(prev =>
          prev?.callsign === msg.callsign ? { ...prev, role: msg.role } : prev
        )
        break
      case 'dissolve':
        toast('The channel has been dissolved.', 'danger')
        setTimeout(() => navigate('/lobby'), 1200)
        break
    }
  }, [navigate, toast])

  // ── Reconnect backfill ────────────────────────────────────────────────────

  const handleReconnect = useCallback(async (lastSeenId: number) => {
    if (!token) return
    try {
      const page = await getTransmissions(channelId, { limit: 50 }, token)
      if (!mountedRef.current) return
      const missed = page.items.filter(w => w.id > lastSeenId).reverse()
      if (missed.length > 0) setTransmissions(prev => mergeTransmissions(prev, missed))
    } catch { /* ignore */ }
  }, [channelId, token])

  // ── Socket ────────────────────────────────────────────────────────────────

  const { wsStatus, sendWhisper, setLastSeen } = useChannelSocket({
    channelId, token: token ?? '', enabled: wsReady,
    onMessage: handleWsMessage, onReconnect: handleReconnect,
  })

  useEffect(() => {
    const prev = prevWsStatus.current
    prevWsStatus.current = wsStatus
    if (prev === wsStatus || prev === '') return
    if (wsStatus === 'reconnecting') {
      toast('Signal lost. Reconnecting…', 'danger')
      playConnectionDrop()
    } else if (wsStatus === 'connected' && prev === 'reconnecting') {
      toast('The channel is open once more.', 'success')
      playReconnected()
    } else if (wsStatus === 'dead') {
      toast('Contact has been lost. Refresh to try again.', 'danger')
    }
  }, [wsStatus, toast])

  useEffect(() => {
    if (transmissions.length > 0) setLastSeen(transmissions[transmissions.length - 1].id)
  }, [transmissions, setLastSeen])

  // ── Load older ────────────────────────────────────────────────────────────

  const loadMore = async () => {
    if (!token || !nextBefore || loadingMore) return
    setLoadingMore(true)
    try {
      const page = await getTransmissions(channelId, { limit: 50, before_id: nextBefore }, token)
      setTransmissions(prev => mergeTransmissions([...page.items].reverse(), prev))
      setNextBefore(page.next_before_id)
    } catch { /* ignore */ } finally { setLoadingMore(false) }
  }

  // ── Send ──────────────────────────────────────────────────────────────────

  const sendDraft = () => {
    const content = draft.trim()
    if (!content || wsStatus !== 'connected') return
    sendWhisper(content)
    playTransmissionSent()
    setDraft('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendDraft() }
  }

  // ── Sound toggle ──────────────────────────────────────────────────────────

  const toggleSound = () => {
    const next = !soundOn
    setSoundOn(next)
    setSoundEnabled(next)
    toast(next ? 'Signal active.' : 'Signal muted.', 'accent')
  }

  // ── Moderation (all callsign-based — no operator_id needed) ──────────────

  const isController = myContact?.role === 'controller'
  const isRelay      = myContact?.role === 'relay'
  const canMod       = isController || isRelay

  const handleKick = async (callsign: string) => {
    if (!token || !canMod) return
    try {
      await kickByCallsign(channelId, callsign, token)
      setContacts(prev => prev.filter(p => p.callsign !== callsign))
      toast(`${callsign} has been removed.`, 'accent')
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Kick failed.', 'danger')
    }
  }

  const handleTransfer = async (callsign: string) => {
    if (!token || !isController) return
    if (!confirm(`Transfer controllership to ${callsign}?`)) return
    try {
      await transferControllerByCallsign(channelId, callsign, token)
      setContacts(prev => prev.map(p =>
        p.callsign === callsign              ? { ...p, role: 'controller' } :
        p.callsign === myContact?.callsign   ? { ...p, role: 'listener'   } :
        p
      ))
      setMyContact(prev => prev ? { ...prev, role: 'listener' } : prev)
      toast('Controllership transferred.', 'accent')
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Transfer failed.', 'danger')
    }
  }

  const handleSetRole = async (callsign: string, role: ContactRole) => {
    if (!token || !isController) return
    try {
      await setRoleByCallsign(channelId, callsign, role, token)
      setContacts(prev => prev.map(p => p.callsign === callsign ? { ...p, role } : p))
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Role change failed.', 'danger')
    }
  }

  const handleRedact = async (transmissionId: number) => {
    if (!token || !canMod) return
    try {
      await redactTransmission(channelId, transmissionId, token)
      setTransmissions(prev => prev.map(w =>
        w.id === transmissionId ? { ...w, is_deleted: true, content: '⸻ redacted ⸻' } : w
      ))
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Redaction failed.', 'danger')
    }
  }

  const handleMintInvite = async () => {
    if (!token || !isController) return
    try {
      const inv = await createCipherKey(channelId, token)
      const url = `${window.location.origin}/invite?token=${encodeURIComponent(inv.token)}`
      await navigator.clipboard.writeText(url)
      setCopying(true)
      toast('Invitation link copied to the clipboard.', 'accent')
      setTimeout(() => setCopying(false), 2000)
    } catch {
      toast('Could not generate an invitation.', 'danger')
    }
  }

  // ── Depart / dissolve ─────────────────────────────────────────────────────

  const handleDepart = async () => {
    if (!token) return
    try { await departChannel(channelId, token) } catch { /* ignore */ }
    navigate('/lobby')
  }

  const handleDissolve = async () => {
    if (!token) return
    if (!confirm('Dissolve this channel? This cannot be undone.')) return
    try { await dissolveChannel(channelId, token) } catch { /* ignore */ }
    navigate('/lobby')
  }

  // ── Render guards ─────────────────────────────────────────────────────────

  if (status === 'loading') {
    return (
      <div className="center-page">
        <div className="spinner" />
        <span>Tuning in…</span>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="center-page">
        <p className="error-msg">{pageError}</p>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/lobby')}>
          ← Return to the lobby
        </button>
      </div>
    )
  }

  const composerPlaceholder =
    wsStatus === 'connected'      ? 'Transmit… (Enter to send, Shift+Enter for newline)'
    : wsStatus === 'reconnecting' ? 'Reconnecting…'
    : 'Contact has been lost'

  return (
    <div className="room-layout">
      {/* Header */}
      <header className="room-header">
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/lobby')}>←</button>
        <span className="room-header-title">{channelName}</span>
        {myContact && (
          <span className="room-header-callsign" title="Your callsign this session">{myContact.callsign}</span>
        )}
        <span className={`ws-status ${wsStatus}`}>{wsStatus}</span>
        <button
          className={`sound-toggle${soundOn ? ' active' : ''}`}
          onClick={toggleSound}
          title={soundOn ? 'Mute signal' : 'Enable signal audio'}
        >📡</button>
        {isController ? (
          <>
            <button className="btn btn-ghost btn-sm" onClick={handleMintInvite}>
              {copying ? 'Copied!' : 'Invite'}
            </button>
            <button className="btn btn-danger btn-sm" onClick={handleDissolve}>Dissolve</button>
          </>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={handleDepart}>Depart</button>
        )}
      </header>

      {/* Body */}
      <div className="room-body">
        {/* Contact sidebar */}
        <aside className="contact-sidebar">
          <div className="contact-sidebar-title">Present</div>
          <div className="contact-list">
            {contacts.map(p => {
              const isMe = p.callsign === myContact?.callsign
              const canTarget = canMod && !isMe && p.role !== 'controller'
              return (
                <div
                  key={p.callsign}
                  className={`contact-item${isMe ? ' is-me' : ''}`}
                >
                  <CallsignSeal callsign={p.callsign} size={22} />
                  <span className="contact-callsign" title={p.callsign}>{p.callsign}</span>
                  {p.role === 'controller' && <span className="contact-role" style={{ color: 'var(--accent)' }}>c</span>}
                  {p.role === 'relay'      && <span className="contact-role" style={{ color: 'var(--muted)' }}>r</span>}
                  {canTarget && (
                    <div className="contact-actions">
                      <button
                        className="contact-action-btn"
                        title="Remove from channel"
                        onClick={() => handleKick(p.callsign)}
                      >✕</button>
                      {isController && p.role === 'listener' && (
                        <button
                          className="contact-action-btn"
                          title="Promote to relay"
                          onClick={() => handleSetRole(p.callsign, 'relay')}
                        >↑</button>
                      )}
                      {isController && p.role === 'relay' && (
                        <button
                          className="contact-action-btn"
                          title="Demote to listener"
                          onClick={() => handleSetRole(p.callsign, 'listener')}
                        >↓</button>
                      )}
                      {isController && (
                        <button
                          className="contact-action-btn"
                          title="Transfer controllership"
                          onClick={() => handleTransfer(p.callsign)}
                        >⇒</button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </aside>

        {/* Feed + composer */}
        <div className="feed-column">
          <div className="feed-scroll">
            {nextBefore !== null && (
              <button className="load-more-btn" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? 'Loading…' : 'Load older transmissions'}
              </button>
            )}

            {transmissions.length === 0 && (
              <p className="empty-state" style={{ marginTop: 48 }}>
                No transmissions yet. Send the first.
              </p>
            )}

            {transmissions.map(t => (
              <div
                key={t.id}
                className={`transmission-row${t.callsign === myContact?.callsign ? ' is-mine' : ''}${t.is_deleted ? ' is-redacted' : ''}`}
              >
                <div className="transmission-header">
                  <CallsignSeal callsign={t.callsign} size={20} />
                  <span
                    className="transmission-callsign"
                    style={{ color: t.callsign === myContact?.callsign ? 'var(--accent)' : 'var(--muted)' }}
                  >
                    {t.callsign}
                  </span>
                  <span className="transmission-time">{formatTime(t.created_at)}</span>
                  {canMod && !t.is_deleted && (
                    <button
                      className="redact-btn"
                      onClick={() => handleRedact(t.id)}
                      title="Redact this transmission"
                    >✕</button>
                  )}
                </div>
                <span className={`transmission-content${t.is_deleted ? ' transmission-redacted' : ''}`}>
                  {t.content}
                </span>
              </div>
            ))}

            <div ref={bottomRef} />
          </div>

          {/* Composer */}
          <div className="composer">
            <textarea
              ref={textareaRef}
              className="composer-input"
              placeholder={composerPlaceholder}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={wsStatus !== 'connected'}
              rows={1}
              maxLength={4000}
            />
            <button
              className="btn btn-primary"
              onClick={sendDraft}
              disabled={wsStatus !== 'connected' || !draft.trim()}
            >Send</button>
          </div>
        </div>
      </div>
    </div>
  )
}
