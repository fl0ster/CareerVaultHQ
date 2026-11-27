import { type PointerEvent, useMemo, useRef, useState } from 'react'
import type { Flow } from '../api.ts'
import Widget from '../Widget.tsx'
import { type LaidLink, type LaidNode, SANKEY, layoutSankey } from './sankey.ts'
import EmptyState from '../../mascot/EmptyState.tsx'

type Tip = { x: number; y: number; title: string; detail: string }

const linkTip = (l: LaidLink): Omit<Tip, 'x' | 'y'> => ({
  title: `${l.sourceLabel} → ${l.targetLabel}`,
  detail: `${l.value.toLocaleString()}${l.share ? ` · ${l.share} of ${l.sourceLabel.toLowerCase()}` : ''}`,
})

const nodeTip = (n: LaidNode): Omit<Tip, 'x' | 'y'> => ({
  title: n.label,
  detail: `${n.value.toLocaleString()}${n.share ? ` · ${n.share} of the stage before` : ''}`,
})

/** Where every scored job ended up: each band is a group of jobs moving from one stage to
 * the next or stopping (not relevant, rejected, still waiting, ...). */
export default function SankeyWidget({ flow }: { flow: Flow }) {
  const layout = useMemo(() => layoutSankey(flow), [flow])
  const wrap = useRef<HTMLDivElement>(null)
  const [tip, setTip] = useState<Tip | null>(null)
  const [active, setActive] = useState<string | null>(null)

  const show = (e: PointerEvent, id: string, content: Omit<Tip, 'x' | 'y'>) => {
    const box = wrap.current?.getBoundingClientRect()
    if (!box) return
    setActive(id)
    setTip({ ...content, x: e.clientX - box.left, y: e.clientY - box.top })
  }
  const hide = () => {
    setActive(null)
    setTip(null)
  }

  // A hovered node highlights the bands touching it; a hovered band only itself.
  const lit = (l: LaidLink) =>
    active === null || active === `${l.source}>${l.target}` || active === l.source || active === l.target

  return (
    <Widget title="Where your job search goes" span="full" href="#/applications" linkLabel="Applications">
      {flow.links.length === 0 ? (
        <EmptyState variant="inline">The flow appears once jobs have been scored.</EmptyState>
      ) : (
        <div className="sankey" ref={wrap} onPointerLeave={hide}>
          <svg
            viewBox={`-4 -4 ${SANKEY.width + 8} ${layout.height + 8}`}
            role="img"
            aria-label="Job search flow from scored jobs to offers; the same numbers follow as a table."
          >
            <g className="sankey-links">
              {layout.links.map((l) => (
                <path
                  key={`${l.source}>${l.target}`}
                  d={l.path}
                  className={`sankey-link sankey--${l.kind}${lit(l) ? '' : ' is-dim'}`}
                  onPointerMove={(e) => show(e, `${l.source}>${l.target}`, linkTip(l))}
                />
              ))}
            </g>
            <g className="sankey-nodes">
              {layout.nodes.map((n) => (
                <g
                  key={n.id}
                  onPointerMove={(e) => show(e, n.id, nodeTip(n))}
                  className={active && active !== n.id && !active.split('>').includes(n.id) ? 'is-dim' : ''}
                >
                  <rect
                    className={`sankey-node sankey--${n.kind}`}
                    x={n.x}
                    y={n.y}
                    width={SANKEY.nodeWidth}
                    height={Math.max(n.height, SANKEY.minBand)}
                    rx={2}
                  />
                  <text className="sankey-label" x={n.x + SANKEY.nodeWidth + 6} y={n.y + Math.max(n.height, 14) / 2} dy="0.35em">
                    <tspan className="sankey-label-name">{n.label}</tspan>
                    <tspan className="sankey-label-value"> {n.value.toLocaleString()}</tspan>
                  </text>
                </g>
              ))}
            </g>
          </svg>
          {tip && (
            <div className="sankey-tip" style={{ left: tip.x, top: tip.y }} role="presentation">
              <strong>{tip.title}</strong>
              <span>{tip.detail}</span>
            </div>
          )}
          <table className="sr-only">
            <caption>Job search flow</caption>
            <thead>
              <tr>
                <th>From</th>
                <th>To</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {layout.links.map((l) => (
                <tr key={`${l.source}>${l.target}`}>
                  <td>{l.sourceLabel}</td>
                  <td>{l.targetLabel}</td>
                  <td>{l.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Widget>
  )
}
