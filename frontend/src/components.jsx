const TONE = {
  SUCCEEDED: 'ok', COMPLETED: 'ok', PUBLISHED: 'ok', ACTIVE: 'ok', SETTLED: 'ok', APPROVED: 'ok', EVALUATED: 'info',
  ELIGIBLE_FOR_ASSESSMENT: 'ok', PARTIALLY_SETTLED: 'warn',
  RUNNING: 'info', IN_PROGRESS: 'info', PENDING: 'warn', SUBMITTED: 'info', CREATED: 'muted', INACTIVE: 'muted',
  RETRY_SCHEDULED: 'warn', INSUFFICIENT_EVIDENCE: 'warn', MANUAL_REVIEW: 'warn', DEFERRED_NO_RESERVE: 'warn',
  FAILED: 'bad', DEAD_LETTER: 'bad', REJECTED: 'bad', NOT_ELIGIBLE: 'bad',
}
export const Badge = ({ value }) => value ? <span className={`badge ${TONE[value] || 'muted'}`}>{value}</span> : <span className="muted">-</span>

export const Table = ({ cols, rows, empty = 'Nothing here yet.' }) => (
  <div className="tablewrap"><table>
    <thead><tr>{cols.map(c => <th key={c.h}>{c.h}</th>)}</tr></thead>
    <tbody>
      {rows?.length ? rows.map((r, i) => <tr key={r.id || i}>{cols.map(c => <td key={c.h}>{c.r(r)}</td>)}</tr>)
        : <tr><td colSpan={cols.length} className="muted">{empty}</td></tr>}
    </tbody>
  </table></div>
)

export const Mono = ({ children }) => <code title={children}>{children}</code>
export const fmt = t => t ? new Date(t).toLocaleTimeString() : '-'
export const Err = ({ error }) => error ? <div className="error">{error}</div> : null
