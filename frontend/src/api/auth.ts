import { post } from './client.js'
import type { LoginRequest, OperatorCreate, OperatorResponse, SocketTokenResponse, TokenResponse } from './types.js'

export const register = (body: OperatorCreate) =>
  post<OperatorResponse>('/auth/register', body)

export const login = (body: LoginRequest) =>
  post<TokenResponse>('/auth/login', body)

/** Mint a one-shot socket token. Must be consumed immediately — 60 s TTL. */
export const getSocketToken = (token: string) =>
  post<SocketTokenResponse>('/auth/socket-token', undefined, token)
