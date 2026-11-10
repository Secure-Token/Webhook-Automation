import { useState } from 'react'
import { api, usePoll } from '../api.js'
import { Badge, Err, Mono, Table, fmt } from '../components.jsx'

export default function Tasks() {
  const { data: tasks, error, reload } = usePoll('/api/v1/tasks')
  const [desc, setDesc] = useState('Add a caching layer to the user service')
  const [opts, setOpts] = useState({ simulate_failure: false, simulate_regression: false, simulate_missing_evidence: false })
  const [sel, setSel] = useState(null)
  const [err, setErr] = useState(null)
  const detail = usePoll(sel ? `/api/v1/tasks/${sel}` : '/health')
  const snaps = usePoll(sel ? `/api/v1/tasks/${sel}/snapshots` : '/health')

  const run = async fn => { try { setErr(null); await fn(); reload() } catch (e) { setErr(e.message) } }
  const create = () => run(async () => { const t = await api('/api/v1/tasks', { method: 'POST', body: { description: desc } }); setSel(t.id) })
  const exec = id => run(() => api(`/api/v1/tasks/${id}/execute`, { method: 'POST', body: opts }))
  const claim = id => run(() => api('/api/v1/claims', { method: 'POST', body: { task_id: id, claim_reason: 'Result did not meet the requirement (demo claim)' } }))

  return (<>
    <h2>Tasks and executions</h2><Err error={error || err} />
    <div className="panel">
      <input className="wide" value={desc} onChange={e => setDesc(e.target.value)} />
      <button onClick={create}>Create task</button>
      <div className="opts">Simulation switches (mock):
        {Object.keys(opts).map(k => (
          <label key={k}><input type="checkbox" checked={opts[k]} onChange={e => setOpts({ ...opts, [k]: e.target.checked })} /> {k.replace('simulate_', '').replace('_', ' ')}</label>
        ))}
      </div>
    </div>
    <Table rows={tasks} cols={[
      { h: 'Task', r: t => <a onClick={() => setSel(t.id)}><Mono>{t.id}</Mono></a> },
      { h: 'Description', r: t => t.description },
      { h: 'Status', r: t => <Badge value={t.status} /> },
      { h: 'Created', r: t => fmt(t.created_at) },
      { h: 'Actions', r: t => <>
        <button disabled={t.status === 'RUNNING'} onClick={() => exec(t.id)}>Execute</button>{' '}
        <button disabled={!['COMPLETED', 'FAILED'].includes(t.status)} onClick={() => claim(t.id)}>Submit claim</button></> },
    ]} />
    {sel && detail.data?.task && <div className="panel">
      <h3>Task <Mono>{sel}</Mono></h3>
      <Table rows={detail.data.executions} cols={[
        { h: 'Execution', r: e => <Mono>{e.id}</Mono> }, { h: 'Status', r: e => <Badge value={e.status} /> },
        { h: 'Model', r: e => `${e.provider}/${e.model}` }, { h: 'Input tokens', r: e => e.input_tokens },
        { h: 'Output tokens', r: e => e.output_tokens }, { h: 'Error', r: e => e.error_message || '-' }]} />
      <h4>Evidence snapshots (mock)</h4>
      <Table rows={Array.isArray(snaps.data) ? snaps.data : []} empty="No snapshots yet." cols={[
        { h: 'Type', r: s => s.snapshot_type }, { h: 'Evidence reference', r: s => <Mono>{s.evidence_ref}</Mono> },
        { h: 'Tests (pass/fail)', r: s => `${s.project_state.tests.passed}/${s.project_state.tests.failed}` },
        { h: 'Files changed', r: s => s.change_summary.files_changed }, { h: 'Captured', r: s => fmt(s.created_at) }]} />
    </div>}
  </>)
}
