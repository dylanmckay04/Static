import { del, get, patch, post } from './client.js'
import type {
  CipherKeyResponse,
  ChannelCreate,
  ChannelDetail,
  ChannelResponse,
  ContactResponse,
  ContactRole,
  OwnContactResponse,
  TransmissionPage,
} from './types.js'

export const listChannels  = (token: string) => get<ChannelResponse[]>('/channels', token)
export const createChannel = (body: ChannelCreate, token: string) => post<ChannelResponse>('/channels', body, token)
export const getChannel    = (id: number, token: string) => get<ChannelDetail>(`/channels/${id}`, token)

export const enterChannel   = (id: number, token: string) => post<OwnContactResponse>(`/channels/${id}/enter`, undefined, token)
export const getMyContact = (id: number, token: string) => get<OwnContactResponse>(`/channels/${id}/contacts/me`, token)
export const departChannel  = (id: number, token: string) => del<void>(`/channels/${id}/depart`, token)
export const dissolveChannel = (id: number, token: string) => del<void>(`/channels/${id}`, token)
export const listContacts = (id: number, token: string) => get<ContactResponse[]>(`/channels/${id}/contacts`, token)

export const getTransmissions = (id: number, params: { limit?: number; before_id?: number }, token: string) => {
  const q = new URLSearchParams()
  if (params.limit     !== undefined) q.set('limit',     String(params.limit))
  if (params.before_id !== undefined) q.set('before_id', String(params.before_id))
  const qs = q.toString()
  return get<TransmissionPage>(`/channels/${id}/transmissions${qs ? `?${qs}` : ''}`, token)
}

export const redactTransmission = (channelId: number, transmissionId: number, token: string) =>
  del<void>(`/channels/${channelId}/transmissions/${transmissionId}`, token)

// ── Controller controls ───────────────────────────────────────────────────────

export const kickOperator = (channelId: number, targetOperatorId: number, token: string) =>
  del<void>(`/channels/${channelId}/contacts/${targetOperatorId}`, token)

export const transferController = (channelId: number, targetOperatorId: number, token: string) =>
  post<void>(`/channels/${channelId}/transfer`, { target_operator_id: targetOperatorId }, token)

export const setOperatorRole = (channelId: number, targetOperatorId: number, role: ContactRole, token: string) =>
  patch<ContactResponse>(`/channels/${channelId}/contacts/${targetOperatorId}/role`, { role }, token)

// ── Cipher keys ───────────────────────────────────────────────────────────────

export const createCipherKey = (channelId: number, token: string, expiresInSeconds = 86400) =>
  post<CipherKeyResponse>(`/channels/${channelId}/cipher-keys?expires_in_seconds=${expiresInSeconds}`, undefined, token)

export const joinViaCipherKey = (inviteToken: string, token: string) =>
  post<OwnContactResponse>(`/channels/join?token=${encodeURIComponent(inviteToken)}`, undefined, token)

// ── Callsign-based controller controls (preferred — no operator_id required) ──

export const kickByCallsign = (channelId: number, callsign: string, token: string) =>
  del<void>(`/channels/${channelId}/contacts/callsign/${encodeURIComponent(callsign)}`, token)

export const transferControllerByCallsign = (channelId: number, targetCallsign: string, token: string) =>
  post<void>(`/channels/${channelId}/transfer/callsign`, { target_callsign: targetCallsign }, token)

export const setRoleByCallsign = (channelId: number, callsign: string, role: ContactRole, token: string) =>
  patch<ContactResponse>(`/channels/${channelId}/contacts/callsign/${encodeURIComponent(callsign)}/role`, { role }, token)
