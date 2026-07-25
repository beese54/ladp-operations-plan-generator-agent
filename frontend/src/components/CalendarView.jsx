import { useEffect, useState } from 'react'

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const STATUS_COLORS = {
  PLANNED: '#60a5fa',
  IN_PROGRESS: '#f59e0b',
  COMPLETED: '#22c55e',
  CANCELLED: '#64748b',
}

function chipColor(op) {
  if ((op.operation_class || '').toUpperCase() === 'EMERGENCY') return '#ef4444'
  return STATUS_COLORS[op.status] || '#64748b'
}

function todayIso() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function fmtTime(iso) {
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

// Read-only monthly operations calendar for the left panel. Auto-switched to
// and navigated by App.jsx (chat-driven); manual prev/next/year controls are
// always available too. Fetches its own data — App only owns year/month.
export default function CalendarView({ year, month, onNavigate }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setSelected(null)
    fetch(`/api/v1/schedule/month?year=${year}&month=${month}`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [year, month])

  function goToMonth(y, m) {
    if (m < 1) { y -= 1; m = 12 }
    if (m > 12) { y += 1; m = 1 }
    onNavigate(y, m)
  }
  const goPrev = () => goToMonth(year, month - 1)
  const goNext = () => goToMonth(year, month + 1)
  const goToday = () => {
    const now = new Date()
    onNavigate(now.getFullYear(), now.getMonth() + 1)
  }

  // Grid cells: leading blanks (Monday-first) from the first day's own
  // server-computed weekday, then the real days, padded to a full row.
  const cells = []
  if (data && data.days.length) {
    const firstDow = data.days[0].weekday // Monday=0 .. Sunday=6
    for (let i = 0; i < firstDow; i++) cells.push(null)
    for (const day of data.days) cells.push(day)
    while (cells.length % 7 !== 0) cells.push(null)
  }

  const today = todayIso()

  return (
    <div style={styles.wrap}>
      <div style={styles.header}>
        <button style={styles.navBtn} onClick={goPrev}>‹</button>
        <span style={styles.monthLabel}>{MONTH_NAMES[month - 1]} {year}</span>
        <button style={styles.navBtn} onClick={goNext}>›</button>
        <button style={styles.todayBtn} onClick={goToday}>Today</button>
        <YearSelect year={year} onChange={y => onNavigate(y, month)} />
        {data && !data.holiday_data_available && (
          <span style={styles.noHolidayNotice}>Holiday data not available for {year} yet</span>
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
        {error && <div style={styles.error}>Calendar load failed: {error}</div>}
        {!error && loading && !data && <div style={styles.loading}>Loading calendar…</div>}
        {!error && data && (
          <>
            <div style={styles.dowRow}>
              {DOW_LABELS.map(l => <div key={l} style={styles.dowCell}>{l}</div>)}
            </div>
            <div style={styles.grid}>
              {cells.map((day, i) => (
                <DayCell
                  key={i}
                  day={day}
                  isToday={!!day && day.date === today}
                  onClick={() => day && setSelected(day)}
                />
              ))}
            </div>
          </>
        )}
        {selected && <DetailPopover day={selected} onClose={() => setSelected(null)} />}
      </div>

      <Legend />
    </div>
  )
}

function YearSelect({ year, onChange }) {
  const nowYear = new Date().getFullYear()
  const ceiling = Math.max(nowYear, year) + 5
  const years = []
  for (let y = 2026; y <= ceiling; y++) years.push(y)
  if (!years.includes(year)) years.push(year)
  years.sort((a, b) => a - b)
  return (
    <select style={styles.yearSelect} value={year} onChange={e => onChange(Number(e.target.value))}>
      {years.map(y => <option key={y} value={y}>{y}</option>)}
    </select>
  )
}

function DayCell({ day, isToday, onClick }) {
  if (!day) return <div style={styles.blankCell} />

  const isWeekend = day.weekday === 5 || day.weekday === 6
  const shade = day.is_holiday ? styles.holidayCell
    : day.is_blackout ? styles.blackoutCell
    : isWeekend ? styles.weekendCell
    : styles.workingCell

  const chips = day.operations.slice(0, 2)
  const overflow = day.operations.length - chips.length

  return (
    <div
      style={{ ...styles.dayCell, ...shade, ...(isToday ? styles.todayRing : {}) }}
      onClick={onClick}
    >
      <div style={styles.dayNum}>{Number(day.date.slice(-2))}</div>
      {day.holiday_name && <div style={styles.holidayLabel}>{day.holiday_name}</div>}
      {chips.map(op => (
        <div key={op.operation_id} style={{ ...styles.chip, borderLeft: `3px solid ${chipColor(op)}` }}>
          {op.pipe_id || op.operation_id}
        </div>
      ))}
      {overflow > 0 && <div style={styles.chipMore}>+{overflow} more</div>}
    </div>
  )
}

function DetailPopover({ day, onClose }) {
  return (
    <div style={styles.detailFloat}>
      <div style={styles.detailFloatHeader}>
        <strong style={{ color: '#f1f5f9', fontSize: 13 }}>{day.date}</strong>
        <button onClick={onClose} style={styles.closeBtn}>✕</button>
      </div>
      <div style={styles.detailFloatBody}>
        {day.is_holiday && (
          <div style={styles.detailRow}>
            <span style={{ color: '#f87171', fontWeight: 600 }}>Public holiday</span>
            {day.holiday_name ? ` — ${day.holiday_name}` : ''}
          </div>
        )}
        {day.is_blackout && (
          <div style={styles.detailRow}>
            <span style={{ color: '#f59e0b', fontWeight: 600 }}>SOP blackout window</span>
            {' '}— no new operation may be planned within 7 days of a holiday
          </div>
        )}
        {day.operations.length === 0 && (
          <div style={{ ...styles.detailRow, color: '#64748b' }}>Nothing scheduled.</div>
        )}
        {day.operations.map(op => (
          <div key={op.operation_id} style={styles.detailOpRow}>
            <div>
              <span style={{ color: chipColor(op), fontWeight: 600 }}>{op.operation_id}</span>
              <span style={{ color: '#94a3b8' }}> · {op.pipe_id} · {op.operation_type} · {op.status}</span>
            </div>
            <div style={{ color: '#64748b', fontSize: 10.5 }}>
              {fmtTime(op.scheduled_start)} → {fmtTime(op.scheduled_end)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Legend() {
  return (
    <div style={styles.legend}>
      <Swatch colour="#7f1d1d" label="Public holiday" />
      <Swatch colour="#78350f" label="Blackout window (±7d)" />
      <Swatch colour="#1e293b" label="Weekend" />
      <Dot colour="#60a5fa" label="Planned" />
      <Dot colour="#f59e0b" label="In progress" />
      <Dot colour="#22c55e" label="Completed" />
      <Dot colour="#ef4444" label="Emergency" />
      <span style={styles.legendHint}>Click a day for details</span>
    </div>
  )
}

function Swatch({ colour, label }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
      <span style={{ width: 12, height: 12, background: colour, borderRadius: 3, display: 'inline-block', flexShrink: 0 }} /> {label}
    </span>
  )
}

function Dot({ colour, label }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
      <span style={{ width: 10, height: 10, borderRadius: '50%', background: colour, display: 'inline-block', flexShrink: 0 }} /> {label}
    </span>
  )
}

const styles = {
  wrap: { display: 'flex', flexDirection: 'column', height: '100%', background: '#0f172a' },
  header: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '7px 12px',
    background: '#1e293b',
    borderBottom: '1px solid #334155',
    flexShrink: 0,
  },
  navBtn: {
    background: 'none', border: '1px solid #475569', borderRadius: 5,
    color: '#cbd5e1', fontSize: 14, width: 26, height: 26, cursor: 'pointer',
  },
  monthLabel: { fontWeight: 700, fontSize: 13, color: '#e2e8f0', minWidth: 130 },
  todayBtn: {
    background: 'none', border: '1px solid #475569', borderRadius: 5,
    color: '#94a3b8', fontSize: 11, padding: '4px 10px', cursor: 'pointer',
  },
  yearSelect: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 5,
    color: '#e2e8f0', fontSize: 12, padding: '3px 6px',
  },
  noHolidayNotice: { color: '#f59e0b', fontSize: 10.5, marginLeft: 'auto' },
  loading: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748b' },
  error: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#f87171', padding: 24, textAlign: 'center' },

  dowRow: { display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', background: '#1e293b', borderBottom: '1px solid #334155' },
  dowCell: { textAlign: 'center', fontSize: 10.5, color: '#64748b', fontWeight: 600, padding: '5px 0', textTransform: 'uppercase' },

  grid: { display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 1, background: '#334155' },
  blankCell: { background: '#0b1220', minHeight: 78 },
  dayCell: { minHeight: 78, padding: '4px 5px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 2 },
  workingCell: { background: '#0f172a' },
  weekendCell: { background: '#161f30' },
  blackoutCell: { background: '#3a2a0f' },
  holidayCell: { background: '#3f1a1a' },
  todayRing: { boxShadow: 'inset 0 0 0 2px #f59e0b' },
  dayNum: { fontSize: 11, color: '#94a3b8', fontWeight: 600 },
  holidayLabel: { fontSize: 9.5, color: '#f87171', fontWeight: 600, lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  chip: {
    fontSize: 9.5, color: '#e2e8f0', background: 'rgba(255,255,255,0.06)',
    borderRadius: 3, padding: '1px 4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  chipMore: { fontSize: 9, color: '#64748b' },

  // Floating detail card — same visual language as GraphCanvas's DetailPanel
  detailFloat: {
    position: 'absolute', top: 12, right: 12, width: 268,
    background: 'rgba(10, 18, 35, 0.94)',
    backdropFilter: 'blur(10px)',
    border: '1px solid rgba(51, 65, 85, 0.85)',
    borderRadius: 8,
    boxShadow: '0 8px 32px rgba(0,0,0,0.55)',
    overflow: 'hidden',
  },
  detailFloatHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '8px 10px', borderBottom: '1px solid rgba(51, 65, 85, 0.5)',
  },
  detailFloatBody: { padding: '8px 10px', maxHeight: 260, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 },
  detailRow: { fontSize: 11.5, color: '#cbd5e1', lineHeight: 1.4 },
  detailOpRow: { fontSize: 11, borderTop: '1px solid rgba(51,65,85,0.5)', paddingTop: 6 },
  closeBtn: { background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: 2 },

  legend: {
    background: '#1e293b', borderTop: '1px solid #334155', padding: '6px 12px',
    display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0, flexWrap: 'wrap',
  },
  legendHint: { color: '#475569', fontSize: 10 },
}
