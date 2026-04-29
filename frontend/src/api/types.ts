// ── Auth ──────────────────────────────────────────────────────────────────────
export interface OperatorCreate    { email: string; password: string }
export interface OperatorResponse  { id: number; email: string; created_at: string }
export interface LoginRequest    { email: string; password: string }
export interface TokenResponse   { access_token: string; token_type: string }
export interface SocketTokenResponse { socket_token: string; jti: string }

// ── Channels ──────────────────────────────────────────────────────────────────
export interface ChannelCreate {
  name: string
  description?: string
  is_encrypted?: boolean
  transmission_ttl_seconds?: number | null
}
export interface ChannelResponse {
  id: number
  name: string
  description: string | null
  is_encrypted: boolean
  transmission_ttl_seconds: number | null
  created_at: string
}
export interface ChannelDetail extends ChannelResponse {
  contact_count: number
}
export interface CipherKeyResponse {
  cipher_key_id: number
  token: string
  expires_at: string
}

// ── Contacts ──────────────────────────────────────────────────────────────────
export type ContactRole = 'controller' | 'relay' | 'listener'
export interface ContactResponse {
  callsign: string
  role: ContactRole
  entered_at: string
}
export interface OwnContactResponse extends ContactResponse {
  channel_id: number
}

// ── Transmissions ─────────────────────────────────────────────────────────────
export interface TransmissionResponse {
  id: number
  channel_id: number
  callsign: string
  content: string
  is_deleted: boolean
  created_at: string
}
export interface TransmissionPage {
  items: TransmissionResponse[]
  next_before_id: number | null
}

// ── WebSocket frames ──────────────────────────────────────────────────────────
export type WsMessage =
  | { op: 'transmission'; id: number; channel_id: number; callsign: string; content: string; is_deleted: boolean; created_at: string }
  | { op: 'enter';   callsign: string }
  | { op: 'depart';  callsign: string }
  | { op: 'dissolve' }
  | { op: 'redact';  transmission_id: number }
  | { op: 'promote'; callsign: string; role: ContactRole }
  | { op: 'error';   detail: string }
