import { useState } from 'react'
import { api, usePoll } from '../api.js'
import { Badge, Err, Mono, Table } from '../components.jsx'

export default function Claims() {
  const { data, error, reload } = usePoll('/api/v1/claims')
  const [err, setErr] = useState(null)
  const [report, setReport] = useState(null)
  const act = async (path, admin, body) => {
    try { setErr(null); await api(path, { method: 'POST', admin, body }); reload() }
    catch (e) { setErr(e.message + (admin ? ' (needs the admin API key)' : '')) }
  }
  const view = async id => setReport(await api(`/api/v1/claims/${id}`))
  return (<>
    <h2>Claims (simulated)</h2><Err error={error || err} />
    <div className="panel muted">Evaluation, adjudication and settlement are separate steps. Credits are DEMO data; settlement is capped by a mock policy limit and reserve.</div>
    <Table rows={data} cols={[
      { h: 'Claim', r: c => <a onClick={() => view(c.id)}><Mono>{c.id}</Mono></a> }, { h: 'Task', r: c => <Mono>{c.task_id}</Mono> },
      { h: 'Reason', r: c => c.claim_reason }, { h: 'Status', r: c => <Badge value={c.status} /> },
      { h: 'Evaluation', r: c => <><Badge value={c.evaluation_status} /> <Badge value={c.evaluation_result} /></> },
      { h: 'Adjudication', r: c => <Badge value={c.adjudication_decision} /> },
      { h: 'Settlement', r: c => <Badge value={c.settlement_status} /> },
      { h: 'Actions', r: c => <>
        <button disabled={c.status !== 'SUBMITTED'} onClick={() => act(`/api/v1/claims/${c.id}/evaluate`, false)}>Evaluate</button>{' '}
        <button disabled={c.status !== 'EVALUATED'} onClick={() => act(`/api/v1/claims/${c.id}/adjudicate`, true, { decision: 'APPROVED' })}>Approve</button>{' '}
        <button disabled={c.status !== 'EVALUATED'} onClick={() => act(`/api/v1/claims/${c.id}/adjudicate`, true, { decision: 'REJECTED' })}>Reject</button>{' '}
        <button disabled={c.status !== 'APPROVED'} onClick={() => act(`/api/v1/claims/${c.id}/settle`, true)}>Settle</button></> }]} />
    {report && <div className="panel"><h3>Claim <Mono>{report.claim.id}</Mono> <button onClick={() => setReport(null)}>Close</button></h3>
      <pre>{JSON.stringify({ evaluation: report.evaluation, settlement: report.settlement }, null, 2)}</pre></div>}
  </>)
}
