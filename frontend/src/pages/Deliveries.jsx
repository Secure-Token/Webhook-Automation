import { useState } from 'react'
import { api, usePoll } from '../api.js'
import { Badge, Err, Mono, Table, fmt } from '../components.jsx'

const STATUSES = ['PENDING', 'IN_PROGRESS', 'SUCCEEDED', 'RETRY_SCHEDULED', 'FAILED', 'DEAD_LETTER']

export default function Deliveries() {
  const [status, setStatus] = useState('')
  const { data, error, reload } = usePoll('/api/v1/webhooks/deliveries' + (status ? `?status=${status}` : ''))
  const [err, setErr] = useState(null)
  const retry = async id => {
    try { setErr(null); await api(`/api/v1/webhooks/deliveries/${id}/retry`, { method: 'POST', admin: true }); reload() }
    catch (e) { setErr(e.message + ' (retry needs the admin API key)') }
  }
  return (<>
    <h2>Webhook deliveries</h2><Err error={error || err} />
    <div className="panel">Filter:{' '}
      <select value={status} onChange={e => setStatus(e.target.value)}>
        <option value="">all</option>{STATUSES.map(s => <option key={s}>{s}</option>)}</select>
      <span className="muted"> Each row is one delivery attempt; an attempt that was retried shows FAILED and the newest attempt shows the current state.</span></div>
    <Table rows={data} cols={[
      { h: 'Delivery', r: d => <Mono>{d.id}</Mono> },
      { h: 'Event', r: d => <><div>{d.event_type}</div><Mono>{d.event_id}</Mono></> },
      { h: 'Subscriber', r: d => d.subscriber_name }, { h: 'Attempt', r: d => d.attempt_number },
      { h: 'HTTP', r: d => d.response_code ?? '-' }, { h: 'Status', r: d => <Badge value={d.delivery_status} /> },
      { h: 'Next retry', r: d => fmt(d.next_retry_at) }, { h: 'Error', r: d => d.error_message || '-' },
      { h: '', r: d => ['RETRY_SCHEDULED', 'FAILED', 'DEAD_LETTER'].includes(d.delivery_status)
        ? <button onClick={() => retry(d.id)}>Retry now</button> : null }]} />
  </>)
}
