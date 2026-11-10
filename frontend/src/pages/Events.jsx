import { useState } from 'react'
import { api, usePoll } from '../api.js'
import { Badge, Err, Mono, Table, fmt } from '../components.jsx'

export default function Events() {
  const { data: events, error } = usePoll('/api/v1/events?limit=200')
  const [payload, setPayload] = useState(null)
  const [err, setErr] = useState(null)
  const open = async id => { try { setErr(null); setPayload(await api(`/api/v1/events/${id}`)) } catch (e) { setErr(e.message) } }
  return (<>
    <h2>Events</h2><Err error={error || err} />
    <Table rows={events} cols={[
      { h: 'Event ID', r: e => <a onClick={() => open(e.id)}><Mono>{e.id}</Mono></a> }, { h: 'Type', r: e => e.event_type },
      { h: 'Task', r: e => e.task_id ? <Mono>{e.task_id}</Mono> : '-' },
      { h: 'Execution', r: e => e.execution_id ? <Mono>{e.execution_id}</Mono> : '-' },
      { h: 'Claim', r: e => e.claim_id ? <Mono>{e.claim_id}</Mono> : '-' }, { h: 'Occurred', r: e => fmt(e.occurred_at) },
      { h: 'Publication', r: e => <Badge value={e.publication_status} /> }]} />
    {payload && <div className="panel"><h3>Payload <Mono>{payload.id}</Mono> <button onClick={() => setPayload(null)}>Close</button></h3>
      <pre>{JSON.stringify(payload.payload, null, 2)}</pre></div>}
  </>)
}
