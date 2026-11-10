import { useState } from 'react'
import { api, usePoll, RECEIVER } from '../api.js'
import { Badge, Err, Mono, Table, fmt } from '../components.jsx'

const EVENTS = ['task.created', 'snapshot.baseline.created', 'execution.started', 'execution.completed', 'execution.failed',
  'snapshot.post.created', 'claim.submitted', 'evaluation.completed', 'claim.adjudicated', 'claim.settled']

export default function Webhooks() {
  const { data: subs, error, reload } = usePoll('/api/v1/webhooks/subscriptions')
  const [name, setName] = useState('Sample receiver')
  const [url, setUrl] = useState('http://receiver:9000/receiver/webhooks/secure-tokens')
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
      { h: 'Endpoint', r: s => <Mono>{s.endpoint_url}</Mono> },
      { h: 'Events', r: s => s.event_types.length === EVENTS.length ? 'all' : s.event_types.join(', ') },
      { h: 'Status', r: s => <Badge value={s.status} /> }, { h: 'Created', r: s => fmt(s.created_at) },
      { h: 'Actions', r: s => <>
        <button onClick={() => run(() => api(`/api/v1/webhooks/subscriptions/${s.id}`, { method: 'PATCH', body: { status: s.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' } }))}>{s.status === 'ACTIVE' ? 'Deactivate' : 'Activate'}</button>{' '}
        <button onClick={() => run(() => api(`/api/v1/webhooks/subscriptions/${s.id}/test`, { method: 'POST' }), d => `Test delivery: ${d.delivery_status} ${d.response_code ?? ''} ${d.error_message ?? ''}`)}>Test</button>{' '}
        <button onClick={() => setHist(s.id)}>History</button></> }]} />
    {hist && <div className="panel"><h3>Delivery history for <Mono>{hist}</Mono></h3>
      <Table rows={Array.isArray(history.data) ? history.data : []} cols={[
        { h: 'Delivery', r: d => <Mono>{d.id}</Mono> }, { h: 'Event', r: d => d.event_type }, { h: 'Attempt', r: d => d.attempt_number },
        { h: 'Status', r: d => <Badge value={d.delivery_status} /> }, { h: 'HTTP', r: d => d.response_code ?? '-' },
        { h: 'Error', r: d => d.error_message || '-' }]} /></div>}
  </>)
}
