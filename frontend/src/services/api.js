// Centralized API layer. Every request to the Flask backend goes through here,
// so components never build URLs or unwrap the response envelope themselves.
// Contract: docs/api.md on Bronson's backend branch.

import axios from 'axios'
import * as mock from './mockData.js'

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? '/api'

// Sample data until the 11/10 integration pass; set VITE_USE_MOCK=false for live Flask.
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

const client = axios.create({ baseURL: API_BASE_URL, timeout: 10000 })

// Error with the backend's stable code so the UI can branch on it.
export class ApiError extends Error {
  constructor(message, { status = null, code = 'NETWORK_ERROR' } = {}) {
    super(message)
    this.status = status
    this.code = code
  }
}

// Backend envelope: { data, meta, error }. Return { data, meta } or throw ApiError.
async function request(config) {
  try {
    const response = await client.request(config)
    return { data: response.data.data, meta: response.data.meta ?? {} }
  } catch (err) {
    const body = err.response?.data?.error
    if (body) {
      throw new ApiError(body.message, { status: err.response.status, code: body.code })
    }
    throw new ApiError('Could not reach the Net Value server.', {
      status: err.response?.status ?? null,
    })
  }
}

// ---- Catalog ----

export function getPlayers({ search = '', page = 1, limit = 20, seasonId, team } = {}) {
  if (USE_MOCK) return mock.getPlayers({ search, page, limit })
  const params = { page, limit }
  if (search) params.search = search
  if (seasonId) params.season_id = seasonId
  if (team) params.team = team
  return request({ method: 'get', url: '/players', params })
}

export function getPlayer(id) {
  if (USE_MOCK) return mock.getPlayer(id)
  return request({ method: 'get', url: `/players/${id}` })
}

export function getTeams() {
  return request({ method: 'get', url: '/teams' })
}

export function getSeasons() {
  return request({ method: 'get', url: '/seasons' })
}

export function projectWins(playerIds, seasonId) {
  return request({
    method: 'post',
    url: '/projections/wins',
    data: { player_ids: playerIds, season_id: seasonId },
  })
}

// ---- Analysis (backend currently returns 501 for these) ----

// Fair value vs. salary for one player. While the model isn't integrated
// (501 NOT_IMPLEMENTED), return nulls flagged `notImplemented` so the UI shows
// "Unavailable" rather than sample numbers next to a real player.
export async function getValuation(playerId) {
  if (USE_MOCK) return mock.getValuation(playerId)
  try {
    return await request({ method: 'post', url: '/valuation', data: { player_id: playerId } })
  } catch (err) {
    if (err.code !== 'NOT_IMPLEMENTED') throw err
    return {
      data: { player_id: playerId, salary: null, predicted_value: null, surplus: null },
      meta: {},
      notImplemented: true,
    }
  }
}

export function validateTrade({ teamASends, teamBSends }) {
  return request({
    method: 'post',
    url: '/trade/validate',
    data: { team_a_sends: teamASends, team_b_sends: teamBSends },
  })
}

export function getPicks({ slot, round, year } = {}) {
  return request({ method: 'get', url: '/picks', params: { slot, round, year } })
}
