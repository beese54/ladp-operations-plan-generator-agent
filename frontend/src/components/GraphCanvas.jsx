import { useRef, useState, useEffect } from 'react'
import CytoscapeComponent from 'react-cytoscapejs'
import cytoscape from 'cytoscape'
import coseBilkent from 'cytoscape-cose-bilkent'

cytoscape.use(coseBilkent)

function edgeWidth(data) {
  const d = Number(data.diameter_mm)
  if (!d) return 2
  if (d >= 400) return 6
  if (d >= 300) return 4
  if (d >= 200) return 3
  return 2
}

const stylesheet = [
  // ── base transitions on everything ──────────────────────────────────────
  {
    selector: 'node, edge',
    style: {
      'transition-property': 'opacity, border-color, line-color, background-color, shadow-opacity',
      'transition-duration': '0.15s',
    },
  },

  // ── Valve nodes ─────────────────────────────────────────────────────────
  {
    selector: 'node[type = "Valve"]',
    style: {
      shape: 'ellipse',
      width: 28,
      height: 28,
      'border-width': 2,
      'border-color': '#0f172a',
      label: 'data(label)',
      'font-size': 8,
      'font-weight': 'bold',
      color: '#e2e8f0',
      'text-valign': 'bottom',
      'text-margin-y': 4,
      'min-zoomed-font-size': 10,
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.65,
      'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle',
    },
  },
  {
    selector: 'node[type = "Valve"][status = "open"]',
    style: {
      'background-gradient-direction': 'to-bottom-right',
      'background-gradient-stop-colors': '#4ade80 #16a34a',
      'background-gradient-stop-positions': '0% 100%',
      'shadow-blur': 14,
      'shadow-color': '#22c55e',
      'shadow-opacity': 0.55,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
    },
  },
  {
    selector: 'node[type = "Valve"][status = "closed"]',
    style: {
      'background-gradient-direction': 'to-bottom-right',
      'background-gradient-stop-colors': '#f87171 #dc2626',
      'background-gradient-stop-positions': '0% 100%',
    },
  },

  // ── Tank nodes ───────────────────────────────────────────────────────────
  {
    selector: 'node[type = "Tank"]',
    style: {
      shape: 'diamond',
      width: 36,
      height: 36,
      'background-gradient-direction': 'to-bottom-right',
      'background-gradient-stop-colors': '#a5b4fc #6366f1',
      'background-gradient-stop-positions': '0% 100%',
      'border-width': 2.5,
      'border-color': '#0f172a',
      'shadow-blur': 14,
      'shadow-color': '#818cf8',
      'shadow-opacity': 0.5,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      label: 'data(label)',
      'font-size': 8,
      'font-weight': 'bold',
      color: '#e2e8f0',
      'text-valign': 'bottom',
      'text-margin-y': 4,
      'min-zoomed-font-size': 10,
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.65,
      'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle',
    },
  },

  // ── Edges ────────────────────────────────────────────────────────────────
  {
    selector: 'edge',
    style: {
      width: ele => edgeWidth(ele.data()),
      'line-color': ele => (ele.data('status') === 'open' ? '#22c55e' : '#ef4444'),
      'target-arrow-color': ele => (ele.data('status') === 'open' ? '#22c55e' : '#ef4444'),
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.7,
      'curve-style': 'bezier',
      opacity: 0.85,
    },
  },
  {
    selector: 'edge[status = "closed"]',
    style: {
      'line-style': 'dashed',
      'line-dash-pattern': [6, 4],
      opacity: 0.28,
    },
  },

  // ── Selected state ───────────────────────────────────────────────────────
  {
    selector: ':selected',
    style: {
      'border-color': '#fbbf24',
      'border-width': 2.5,
      'line-color': '#fbbf24',
      'target-arrow-color': '#fbbf24',
      'shadow-blur': 22,
      'shadow-color': '#fbbf24',
      'shadow-opacity': 0.9,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      opacity: 1,
    },
  },
  {
    selector: 'edge:selected',
    style: {
      label: 'data(pipe_id)',
      'font-size': 9,
      'font-weight': 'bold',
      color: '#fbbf24',
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.85,
      'text-background-padding': '3px',
      'text-background-shape': 'roundrectangle',
      'text-rotation': 'autorotate',
    },
  },

  // ── Hover neighbourhood dimming ──────────────────────────────────────────
  {
    selector: '.faded',
    style: { opacity: 0.08 },
  },

  // ── Pipe trace — background dim ─────────────────────────────────────────
  {
    selector: '.trace-dimmed',
    style: { opacity: 0.1 },
  },

  // ── Pipe trace — highlighted pipe ────────────────────────────────────────
  {
    selector: 'edge.traced',
    style: {
      'line-color': '#f59e0b',
      'target-arrow-color': '#f59e0b',
      label: 'data(pipe_id)',
      'font-size': 9,
      'font-weight': 'bold',
      color: '#f59e0b',
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.85,
      'text-background-padding': '3px',
      'text-background-shape': 'roundrectangle',
      'text-rotation': 'autorotate',
      width: 4,
      'shadow-blur': 14,
      'shadow-color': '#f59e0b',
      'shadow-opacity': 0.65,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      opacity: 1,
    },
  },

  // ── Pipe trace — origin pipe (the searched pipe) ─────────────────────────
  {
    selector: 'edge.traced-origin',
    style: {
      'line-color': '#ffffff',
      'target-arrow-color': '#ffffff',
      label: 'data(pipe_id)',
      'font-size': 11,
      'font-weight': 'bold',
      color: '#ffffff',
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.9,
      'text-background-padding': '4px',
      'text-background-shape': 'roundrectangle',
      'text-rotation': 'autorotate',
      width: 7,
      'shadow-blur': 30,
      'shadow-color': '#ffffff',
      'shadow-opacity': 1,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      opacity: 1,
    },
  },

  // ── Pipe trace — highlighted intermediate valve ───────────────────────────
  {
    selector: 'node.traced',
    style: {
      'border-color': '#f59e0b',
      'border-width': 3.5,
      'shadow-blur': 18,
      'shadow-color': '#f59e0b',
      'shadow-opacity': 0.85,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      opacity: 1,
    },
  },

  // ── Pipe trace — tail-end valve ───────────────────────────────────────────
  {
    selector: 'node.traced-tail',
    style: {
      'border-color': '#ec4899',
      'border-width': 4,
      'shadow-blur': 24,
      'shadow-color': '#ec4899',
      'shadow-opacity': 0.9,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      opacity: 1,
    },
  },

  // ── Hovered edge — show pipe_id label ────────────────────────────────────
  {
    selector: 'edge.hovered',
    style: {
      label: 'data(pipe_id)',
      'font-size': 9,
      'font-weight': 'bold',
      color: '#38bdf8',
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.85,
      'text-background-padding': '3px',
      'text-background-shape': 'roundrectangle',
      'text-rotation': 'autorotate',
      'line-color': '#38bdf8',
      'target-arrow-color': '#38bdf8',
      opacity: 1,
    },
  },

  // ── Upstream valve (source / supply side) when a pipe is hovered ─────────
  {
    selector: 'node.pipe-upstream',
    style: {
      'border-color': '#60a5fa',
      'border-width': 4,
      'shadow-blur': 22,
      'shadow-color': '#60a5fa',
      'shadow-opacity': 0.95,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      opacity: 1,
    },
  },

  // ── Downstream valve (target / demand side) when a pipe is hovered ───────
  {
    selector: 'node.pipe-downstream',
    style: {
      'border-color': '#fb923c',
      'border-width': 4,
      'shadow-blur': 22,
      'shadow-color': '#fb923c',
      'shadow-opacity': 0.95,
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      opacity: 1,
    },
  },
]

const layout = {
  name: 'cose-bilkent',
  animate: false,
  randomize: true,
  nodeRepulsion: 25000,
  idealEdgeLength: 120,
  edgeElasticity: 0.45,
  gravity: 0.08,
  gravityRange: 1.5,
  gravityCompound: 1.0,
  gravityRangeCompound: 1.5,
  numIter: 5000,
  tile: true,
  tilingPaddingVertical: 10,
  tilingPaddingHorizontal: 10,
  nodeDimensionsIncludeLabels: false,
}

export default function GraphCanvas({ nodes, edges, trace = null }) {
  const cyRef = useRef(null)
  const [selected, setSelected] = useState(null)

  const elements = [
    ...nodes,
    ...edges.map(e => ({ ...e, data: { ...e.data, id: e.data.id } })),
  ]

  // Apply / clear trace highlighting whenever the trace result changes
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    cy.elements().removeClass('traced traced-tail traced-origin trace-dimmed')
    if (!trace) return

    cy.elements().addClass('trace-dimmed')

    const tailSet = new Set(trace.tail_valve_ids)
    trace.pipe_ids.forEach(id => {
      cy.getElementById(id).removeClass('trace-dimmed').addClass('traced')
    })
    trace.valve_ids.forEach(id => {
      const el = cy.getElementById(id)
      el.removeClass('trace-dimmed')
      el.addClass(tailSet.has(id) ? 'traced-tail' : 'traced')
    })
    // Origin pipe overrides the generic traced style — always visible and labelled
    cy.getElementById(trace.origin_pipe_id)
      .removeClass('traced trace-dimmed')
      .addClass('traced-origin')
  }, [trace])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    const onTap = e => {
      if (e.target === cy) { setSelected(null); return }
      setSelected(e.target.data())
    }
    const onMouseOver = e => {
      if (e.target === cy) return
      cy.elements().not(e.target.closedNeighborhood()).addClass('faded')
      if (e.target.isEdge()) {
        e.target.addClass('hovered')
        e.target.source().addClass('pipe-upstream')
        e.target.target().addClass('pipe-downstream')
      }
    }
    const onMouseOut = () => {
      cy.elements().removeClass('faded hovered pipe-upstream pipe-downstream')
    }

    cy.on('tap', onTap)
    cy.on('mouseover', 'node, edge', onMouseOver)
    cy.on('mouseout', 'node, edge', onMouseOut)

    return () => {
      cy.removeListener('tap', onTap)
      cy.removeListener('mouseover', onMouseOver)
      cy.removeListener('mouseout', onMouseOut)
    }
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>
      <CytoscapeComponent
        cy={cy => { cyRef.current = cy }}
        elements={elements}
        stylesheet={stylesheet}
        layout={layout}
        style={{ flex: 1, background: '#0f172a' }}
        wheelSensitivity={0.3}
      />
      <Legend />
      {selected && (
        <div style={{ position: 'absolute', bottom: 48, left: 12, zIndex: 10 }}>
          <DetailPanel data={selected} onClose={() => setSelected(null)} />
        </div>
      )}
    </div>
  )
}

function DetailPanel({ data, onClose }) {
  const isPipe  = 'pipe_id' in data
  const isTank  = data.type === 'Tank'
  const typeLabel = isPipe ? 'PIPE' : isTank ? 'TANK' : 'VALVE'
  const typeColor = isPipe ? '#38bdf8' : isTank ? '#818cf8' : '#4ade80'

  const skip = new Set(['id', 'source', 'target', 'label', 'type'])
  const entries = Object.entries(data).filter(([k]) => !skip.has(k))

  return (
    <div style={styles.detailFloat}>
      <div style={styles.detailFloatHeader}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ ...styles.typeBadge, color: typeColor, borderColor: typeColor + '55', background: typeColor + '18' }}>
            {typeLabel}
          </span>
          <strong style={{ color: '#f1f5f9', fontSize: 13 }}>{data.pipe_id || data.id}</strong>
        </div>
        <button onClick={onClose} style={styles.closeBtn}>✕</button>
      </div>
      <div style={styles.detailFloatBody}>
        {entries.map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <span style={styles.detailKey}>{k.replace(/_/g, ' ')}</span>
            <span style={detailValueStyle(k, v)}>{String(v ?? '—')}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function detailValueStyle(key, value) {
  if (key === 'status') {
    return { color: value === 'open' ? '#22c55e' : '#ef4444', fontWeight: 600 }
  }
  return { color: '#cbd5e1' }
}

function Legend() {
  return (
    <div style={styles.legend}>
      <Dot colour="#22c55e" label="Open valve" />
      <Dot colour="#ef4444" label="Closed valve" />
      <Dot colour="#818cf8" shape="diamond" label="Tank" />
      <Dot colour="#60a5fa" label="Upstream valve" />
      <Dot colour="#fb923c" label="Downstream valve" />
      <span style={styles.legendHint}>── open pipe &nbsp;╌ closed pipe</span>
      <span style={styles.legendHint}>Scroll to zoom · Hover pipe to trace flow · Click to inspect</span>
    </div>
  )
}

function Dot({ colour, shape = 'circle', label }) {
  const s = shape === 'diamond'
    ? { width: 10, height: 10, background: colour, transform: 'rotate(45deg)', display: 'inline-block', flexShrink: 0 }
    : { width: 10, height: 10, borderRadius: '50%', background: colour, display: 'inline-block', flexShrink: 0 }
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
      <span style={s} /> {label}
    </span>
  )
}

const styles = {
  // Floating detail card (absolutely positioned over the canvas)
  detailFloat: {
    width: 268,
    background: 'rgba(10, 18, 35, 0.94)',
    backdropFilter: 'blur(10px)',
    border: '1px solid rgba(51, 65, 85, 0.85)',
    borderRadius: 8,
    boxShadow: '0 8px 32px rgba(0,0,0,0.55)',
    overflow: 'hidden',
  },
  detailFloatHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 10px',
    borderBottom: '1px solid rgba(51, 65, 85, 0.5)',
  },
  typeBadge: {
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: '0.07em',
    padding: '2px 6px',
    borderRadius: 4,
    border: '1px solid',
    flexShrink: 0,
  },
  detailFloatBody: {
    padding: '8px 10px',
    maxHeight: 220,
    overflowY: 'auto',
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '4px 12px',
    alignItems: 'start',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: '#64748b',
    cursor: 'pointer',
    fontSize: 14,
    lineHeight: 1,
    padding: 2,
  },
  detailKey: { fontSize: 11, color: '#64748b', padding: '1px 0', textTransform: 'capitalize' },
  legend: {
    background: '#1e293b',
    borderTop: '1px solid #334155',
    padding: '6px 12px',
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    flexShrink: 0,
    flexWrap: 'wrap',
  },
  legendHint: { color: '#475569', fontSize: 10 },
}
