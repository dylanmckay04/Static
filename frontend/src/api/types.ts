// ── Auth ──────────────────────────────────────────────────────────────────────
export interface SeekerCreate    { email: string; password: string }
export interface SeekerResponse  { id: number; email: string; created_at: string }
export interface LoginRequest    { email: string; password: string }
export interface TokenResponse   { access_token: string; token_type: string }
export interface SocketTokenResponse { socket_token: string; jti: string }

// ── Seances ───────────────────────────────────────────────────────────────────
export interface SeanceCreate {
  name: string
  description?: string
  is_sealed?: boolean
  whisper_ttl_seconds?: number | null
}
export interface SeanceResponse {
  id: number
  name: string
  description: string | null
  is_sealed: boolean
  whisper_ttl_seconds: number | null
  created_at: string
}
export interface SeanceDetail extends SeanceResponse {
  presence_count: number
}
export interface InviteResponse {
  invite_id: number
  token: string
  expires_at: string
}

// ── Presences ─────────────────────────────────────────────────────────────────
export type PresenceRole = 'warden' | 'moderator' | 'attendant'
export interface PresenceResponse {
  sigil: string
  role: PresenceRole
  entered_at: string
}
export interface OwnPresenceResponse extends PresenceResponse {
  seance_id: number
}

// ── Whispers ──────────────────────────────────────────────────────────────────
export interface WhisperResponse {
  id: number
  seance_id: number
  sigil: string
  content: string
  is_deleted: boolean
  created_at: string
}
export interface WhisperPage {
  items: WhisperResponse[]
  next_before_id: number | null
}

// ── WebSocket frames ──────────────────────────────────────────────────────────
export type WsMessage =
  | { op: 'whisper'; id: number; seance_id: number; sigil: string; content: string; is_deleted: boolean; created_at: string }
  | { op: 'enter';   sigil: string }
  | { op: 'depart';  sigil: string }
  | { op: 'dissolve' }
  | { op: 'redact';  whisper_id: number }
  | { op: 'promote'; sigil: string; role: PresenceRole }
  | { op: 'error';   detail: string }
