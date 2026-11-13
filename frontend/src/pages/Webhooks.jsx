import { useState } from 'react'
import { api, usePoll, RECEIVER } from '../api.js'
import { Badge, Err, Mono, Table, fmt } from '../components.jsx'

const EVENTS = ['task.created', 'snapshot.baseline.created', 'execution.started', 'execution.completed', 'execution.failed',
  'snapshot.post.created', 'claim.submitted', 'evaluation.completed', 'claim.adjudicated', 'claim.settled']

export default function Webhooks() {
  const { data: subs, error, reload } = usePoll('/api/v1/webhooks/subscriptions')
  const [name, setName] = useState('Sample receiver')
  // Default suits lite mode (no Docker). Under Docker Compose set VITE_DEFAULT_WEBHOOK_URL at build time to
  // http://receiver:9000/receiver/webhooks/secure-tokens, since `receiver` only resolves inside the compose network.
  const [url, setUrl] = useState(
    import.meta.env.VITE_DEFAULT_WEBHOOK_URL || 'http://localhost:9000/receiver/webhooks/secure-tokens')
  const [types, setTypes] = useState(new Set(EVENTS))
  const [created, setCreated] = useState(null)
  const [msg, setMsg] = useState(null)
  const [err, setErr] = useState(null)
  const [hist, setHist] = useState(null)
  const history = usePoll(hist ? `/api/v1/webhooks/deliveries?subscription_id=${hist}` : '/health')

  const run = async (fn, ok) => {
    try { setErr(null); setMsg(null); const r = await fn(); if (ok) setMsg(ok(r)); reload(); return r } catch (e) { setErr(e.message) }
  }
  const toggle = t => { const s = new Set(types); s.has(t) ? s.delete(t) : s.add(t); setTypes(s) }
  const create = async () => {
    const r = await run(() => api('/api/v1/webhooks/subscriptions', { method: 'POST', body: { subscriber_name: name, endpoint_url: url, event_types: [...types] } }))
    if (r) setCreated(r)
  }
  const [edit, setEdit] = useState(null) // { id, value } while a row's URL is being edited inline
  const saveUrl = async () => {
    const next = edit.value.trim()
    if (!next) { setErr('Endpoint URL cannot be empty'); return }
    const r = await run(() => api(`/api/v1/webhooks/subscriptions/${edit.id}`, { method: 'PATCH', body: { endpoint_url: next } }),
      () => 'Endpoint updated. Use "Retry now" on the Deliveries page (admin key) or wait for the next scheduled retry.')
    if (r) setEdit(null)
  }
  const configureReceiver = async () => {
    try {
      const r = await fetch(RECEIVER + '/receiver/config/secret', {
        method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-Receiver-Token': 'receiver_dev_token' },
        body: JSON.stringify({ subscription_id: created.id, secret: created.signing_secret }) })
      setMsg(r.ok ? 'Sample receiver configured with this secret.' : 'Receiver rejected the configuration.')
    } catch { setMsg('Could not reach the sample receiver at ' + RECEIVER) }
  }

  return (<>
    <h2>Webhook subscriptions</h2><Err error={error || err} />{msg && <div className="info-msg">{msg}</div>}
    <div className="panel">
      <input value={name} onChange={e => setName(e.target.value)} placeholder="Subscriber name" />
      <input className="wide" value={url} onChange={e => setUrl(e.target.value)} placeholder="Endpoint URL" />
      <div className="opts">{EVENTS.map(t => (
        <label key={t}><input type="checkbox" checked={types.has(t)} onChange={() => toggle(t)} /> {t}</label>))}</div>
      <button onClick={create} disabled={!types.size}>Register subscriber</button>
    </div>
    {created && <div className="panel secret">
      <b>Signing secret (shown once, store it now):</b> <code>{created.signing_secret}</code>
      <div><button onClick={configureReceiver}>Configure sample receiver with this secret</button>{' '}
        <button onClick={() => setCreated(null)}>Dismiss</button></div>
    </div>}
    <Table rows={subs} cols={[
      { h: 'Subscription', r: s => <Mono>{s.id}</Mono> }, { h: 'Subscriber', r: s => s.subscriber_name },
      { h: 'Endpoint', r: s => <code className="endpoint" title={s.endpoint_url}>{s.endpoint_url.split(/(?<=\/)/).map((p, i) => <span key={i}>{p}<wbr /></span>)}</code> },
      { h: 'Events', r: s => s.event_types.length === EVENTS.length ? 'all' : s.event_types.join(', ') },
      { h: 'Status', r: s => <Badge value={s.status} /> }, { h: 'Created', r: s => fmt(s.created_at) },
      { h: 'Actions', r: s => <>
        <button onClick={() => run(() => api(`/api/v1/webhooks/subscriptions/${s.id}`, { method: 'PATCH', body: { status: s.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' } }))}>{s.status === 'ACTIVE' ? 'Deactivate' : 'Activate'}</button>{' '}
        <button onClick={() => run(() => api(`/api/v1/webhooks/subscriptions/${s.id}/test`, { method: 'POST' }), d => `Test delivery: ${d.delivery_status} ${d.response_code ?? ''} ${d.error_message ?? ''}`)}>Test</button>{' '}
        {edit?.id === s.id
          ? <><input className="wide" value={edit.value} onChange={e => setEdit({ ...edit, value: e.target.value })}
              onKeyDown={e => e.key === 'Enter' && saveUrl()} autoFocus />{' '}
            <button onClick={saveUrl}>Save</button>{' '}<button onClick={() => setEdit(null)}>Cancel</button>{' '}</>
          : <><button onClick={() => setEdit({ id: s.id, value: s.endpoint_url })}>Edit URL</button>{' '}</>}
        <button onClick={() => setHist(s.id)}>History</button></> }]} />
    {hist && <div className="panel"><h3>Delivery history for <Mono>{hist}</Mono></h3>
      <Table rows={Array.isArray(history.data) ? history.data : []} cols={[
        { h: 'Delivery', r: d => <Mono>{d.id}</Mono> }, { h: 'Event', r: d => d.event_type }, { h: 'Attempt', r: d => d.attempt_number },
        { h: 'Status', r: d => <Badge value={d.delivery_status} /> }, { h: 'HTTP', r: d => d.response_code ?? '-' },
        { h: 'Error', r: d => d.error_message || '-' }]} /></div>}
  </>)
}
