import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

// Global view state: brand, period, comparison and filters. Kept in the URL hash
// so a view can be bookmarked or shared, and every page reads it from here, so
// changing the brand re-renders every chart (the old dashboard's static-chart bug).

const DEFAULT = { page: 'overview', brand: 'Dettol', period: 'YTD', mode: 'yoy', retailers: [], channels: [], tiers: [], regions: [] }
const LISTS = ['retailers', 'channels', 'tiers', 'regions']

function readHash() {
  const p = new URLSearchParams(window.location.hash.slice(1))
  const s = { ...DEFAULT }
  for (const k of Object.keys(DEFAULT)) {
    const v = p.get(k)
    if (v == null) continue
    s[k] = LISTS.includes(k) ? v.split(',').filter(Boolean) : v
  }
  return s
}

function writeHash(s) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(s)) {
    if (LISTS.includes(k)) { if (v.length) p.set(k, v.join(',')) } else if (v !== DEFAULT[k]) p.set(k, v)
  }
  const h = p.toString()
  if (window.location.hash.slice(1) !== h) window.history.replaceState(null, '', h ? `#${h}` : window.location.pathname)
}

const Ctx = createContext(null)

export function ViewProvider({ children }) {
  const [view, setView] = useState(readHash)
  useEffect(() => writeHash(view), [view])
  const set = useCallback((patch) => setView((v) => ({ ...v, ...patch })), [])
  return <Ctx.Provider value={{ view, set }}>{children}</Ctx.Provider>
}

export const useView = () => useContext(Ctx)

// Query string for the API from the view (everything except page and brand)
export function viewQuery(view, extra = {}) {
  const p = new URLSearchParams({ period: view.period, mode: view.mode })
  for (const k of LISTS) if (view[k].length) p.set(k, view[k].join(','))
  for (const [k, v] of Object.entries(extra)) if (v != null && v !== '') p.set(k, v)
  return p.toString()
}

// ---------------------------------------------------------------- data hook
const cache = new Map()

export async function getJSON(url) {
  if (cache.has(url)) return cache.get(url)
  const r = await fetch(url)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.detail || `Request failed (${r.status})`)
  cache.set(url, body)
  return body
}

// Fetches `url` and refetches whenever it changes. Keeps the previous data on
// screen (dimmed) while the new view loads, so the layout doesn't jump.
export function useApi(url) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const latest = useRef(url)
  useEffect(() => {
    if (!url) return
    latest.current = url
    setState((s) => ({ ...s, loading: true, error: null }))
    getJSON(url)
      .then((data) => latest.current === url && setState({ data, error: null, loading: false }))
      .catch((e) => latest.current === url && setState({ data: null, error: e.message, loading: false }))
  }, [url])
  return state
}

export function useBrandApi(page, extra) {
  const { view } = useView()
  const url = useMemo(
    () => `/api/brands/${encodeURIComponent(view.brand)}/${page}?${viewQuery(view, extra)}`,
    [view.brand, view.period, view.mode, view.retailers, view.channels, view.tiers, view.regions, page, JSON.stringify(extra || {})],
  )
  return useApi(url)
}
