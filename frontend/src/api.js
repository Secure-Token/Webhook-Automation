import { useEffect, useState, useCallback } from 'react'

export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const RECEIVER = import.meta.env.VITE_RECEIVER_URL || 'http://localhost:9000'

const store = {
  get devKey() { return localStorage.getItem('st_dev_key') || 'st_dev_demo_key' },
  get adminKey() { return localStorage.getItem('st_admin_key') || '' },
}
export const keys = store
export const setKeys = (dev, admin) => { localStorage.setItem('st_dev_key', dev); localStorage.setItem('st_admin_key', admin) }

export async function api(path, { method = 'GET', body, admin = false } = {}) {
  const res = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-API-Key': admin ? store.adminKey : store.devKey },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.error?.message || `HTTP ${res.status}`)
  return data
}

// Poll an endpoint every few seconds so the dashboard reflects live workflow state.
export function usePoll(path, { admin = false, interval = 3000 } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const reload = useCallback(async () => {
    try { setData(await api(path, { admin })); setError(null) } catch (e) { setError(e.message) }
  }, [path, admin])
  useEffect(() => { reload(); const t = setInterval(reload, interval); return () => clearInterval(t) }, [reload, interval])
  return { data, error, reload }
}
