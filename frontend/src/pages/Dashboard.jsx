import { usePoll } from '../api.js'
import { Err } from '../components.jsx'

const Card = ({ label, value, tone }) => (
  <div className={`card ${tone || ''}`}><div className="v">{value ?? '-'}</div><div className="l">{label}</div></div>
)

export default function Dashboard() {
  const { data: s, error } = usePoll('/api/v1/stats')
  return (<>
    <h2>Overview</h2><Err error={error} />
    {s && <>
      <h3>Workflow</h3>
      <div className="cards">
        <Card label="Total tasks" value={s.tasks} />
        <Card label="Running executions" value={s.executions_running} tone="info" />
        <Card label="Completed executions" value={s.executions_completed} tone="ok" />
        <Card label="Failed executions" value={s.executions_failed} tone="bad" />
        <Card label="Tokens, mock (input + output)" value={`${s.tokens_total} (${s.tokens_input} + ${s.tokens_output})`} />
      </div>
      <h3>Events and webhooks</h3>
      <div className="cards">
        <Card label="Events" value={s.events} />
        <Card label="Events awaiting publication" value={s.events_unpublished} tone={s.events_unpublished ? 'warn' : ''} />
        <Card label="Successful deliveries" value={s.deliveries_succeeded} tone="ok" />
        <Card label="Failed delivery attempts" value={s.deliveries_failed} tone="bad" />
        <Card label="Pending retries" value={s.deliveries_pending_retry} tone="warn" />
      </div>
      <h3>Claims (simulated)</h3>
      <div className="cards">
        <Card label="Claims submitted" value={s.claims_submitted} />
        <Card label="Evaluations completed" value={s.evaluations_completed} />
        <Card label="Settlements processed" value={s.settlements_processed} tone="ok" />
        <Card label="Mock reserve balance (demo credits)" value={s.reserve_balance_demo} />
      </div>
    </>}
  </>)
}
