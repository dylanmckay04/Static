import { del, get, patch, post } from './client.js'
import type {
  InviteResponse,
  OwnPresenceResponse,
  PresenceResponse,
  PresenceRole,
  SeanceCreate,
  SeanceDetail,
  SeanceResponse,
  WhisperPage,
} from './types.js'

export const listSeances  = (token: string) => get<SeanceResponse[]>('/seances', token)
export const createSeance = (body: SeanceCreate, token: string) => post<SeanceResponse>('/seances', body, token)
export const getSeance    = (id: number, token: string) => get<SeanceDetail>(`/seances/${id}`, token)

export const enterSeance  = (id: number, token: string) => post<OwnPresenceResponse>(`/seances/${id}/enter`, undefined, token)
export const getMyPresence = (id: number, token: string) => get<OwnPresenceResponse>(`/seances/${id}/presences/me`, token)
export const departSeance  = (id: number, token: string) => del<void>(`/seances/${id}/depart`, token)
export const dissolveSeance = (id: number, token: string) => del<void>(`/seances/${id}`, token)
export const listPresences = (id: number, token: string) => get<PresenceResponse[]>(`/seances/${id}/presences`, token)

export const getWhispers = (id: number, params: { limit?: number; before_id?: number }, token: string) => {
  const q = new URLSearchParams()
  if (params.limit     !== undefined) q.set('limit',     String(params.limit))
  if (params.before_id !== undefined) q.set('before_id', String(params.before_id))
  const qs = q.toString()
  return get<WhisperPage>(`/seances/${id}/whispers${qs ? `?${qs}` : ''}`, token)
}

export const redactWhisper = (seanceId: number, whisperId: number, token: string) =>
  del<void>(`/seances/${seanceId}/whispers/${whisperId}`, token)

// ── Warden controls ───────────────────────────────────────────────────────────

export const kickPresence = (seanceId: number, targetSeekerId: number, token: string) =>
  del<void>(`/seances/${seanceId}/presences/${targetSeekerId}`, token)

export const transferWardenship = (seanceId: number, targetSeekerId: number, token: string) =>
  post<void>(`/seances/${seanceId}/transfer`, { target_seeker_id: targetSeekerId }, token)

export const setPresenceRole = (seanceId: number, targetSeekerId: number, role: PresenceRole, token: string) =>
  patch<PresenceResponse>(`/seances/${seanceId}/presences/${targetSeekerId}/role`, { role }, token)

// ── Invites ───────────────────────────────────────────────────────────────────

export const createInvite = (seanceId: number, token: string, expiresInSeconds = 86400) =>
  post<InviteResponse>(`/seances/${seanceId}/invites?expires_in_seconds=${expiresInSeconds}`, undefined, token)

export const joinViaInvite = (inviteToken: string, token: string) =>
  post<OwnPresenceResponse>(`/seances/join?token=${encodeURIComponent(inviteToken)}`, undefined, token)

// ── Sigil-based warden controls (preferred — no seeker_id required) ────────

export const kickBySigil = (seanceId: number, sigil: string, token: string) =>
  del<void>(`/seances/${seanceId}/presences/sigil/${encodeURIComponent(sigil)}`, token)

export const transferWardenshipBySigil = (seanceId: number, targetSigil: string, token: string) =>
  post<void>(`/seances/${seanceId}/transfer/sigil`, { target_sigil: targetSigil }, token)

export const setRoleBySigil = (seanceId: number, sigil: string, role: PresenceRole, token: string) =>
  patch<PresenceResponse>(`/seances/${seanceId}/presences/sigil/${encodeURIComponent(sigil)}/role`, { role }, token)
