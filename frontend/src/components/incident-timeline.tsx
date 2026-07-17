import { useMemo } from "react"
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { Scan } from "@/lib/api"

/*
 * Historical incident timeline — Recharts dark-tuned per the design
 * tokens: canvas-black plot, hairline grid, ink text, risk line in the
 * threat vocabulary (flagged points accent-red, changed accent-orange,
 * clean accent-green). The flag threshold renders as a reference line so
 * "why was this one flagged" is answerable at a glance.
 */

const INK = "#fcfdff"
const MUTE = "#a1a4a5"
const HAIRLINE = "rgba(255,255,255,0.06)"
const HAIRLINE_STRONG = "rgba(255,255,255,0.14)"
const GREEN = "#11ff99"
const ORANGE = "#ff801f"
const RED = "#ff2047"

interface Point {
  time: number
  risk: number
  verdict: string
  id: string
}

function verdictColor(verdict: string): string {
  if (verdict === "flagged") return RED
  if (verdict === "changed") return ORANGE
  return GREEN
}

function TimelineTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: { payload: Point }[]
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-md border border-hairline-strong bg-surface-elevated px-3 py-2">
      <p className="text-caption text-charcoal">{new Date(p.time).toLocaleString()}</p>
      <p className="text-body-sm" style={{ color: verdictColor(p.verdict) }}>
        {Math.round(p.risk * 100)}% risk · {p.verdict}
      </p>
    </div>
  )
}

export function IncidentTimeline({
  scans,
  threshold,
  onPointClick,
  height = 220,
}: {
  scans: Scan[]
  threshold: number
  onPointClick?: (scanId: string) => void
  height?: number
}) {
  const data = useMemo<Point[]>(
    () =>
      scans
        .filter((s) => s.status === "completed" && s.risk_score != null && s.verdict)
        .map((s) => ({
          time: new Date(s.finished_at ?? s.created_at).getTime(),
          risk: s.risk_score!,
          verdict: s.verdict!,
          id: s.id,
        }))
        .sort((a, b) => a.time - b.time),
    [scans]
  )

  if (data.length < 2) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-hairline-strong bg-surface-card"
        style={{ height }}
      >
        <p className="text-body-sm text-mute">
          The timeline appears after a few completed scans.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-hairline-strong bg-surface-card p-4">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke={HAIRLINE} vertical={false} />
          <XAxis
            dataKey="time"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t: number) =>
              new Date(t).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              }) +
              " " +
              new Date(t).toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })
            }
            tick={{ fill: MUTE, fontSize: 11 }}
            stroke={HAIRLINE_STRONG}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fill: MUTE, fontSize: 11 }}
            stroke={HAIRLINE_STRONG}
            tickLine={false}
          />
          <Tooltip content={<TimelineTooltip />} cursor={{ stroke: HAIRLINE_STRONG }} />
          <ReferenceLine
            y={threshold}
            stroke={RED}
            strokeOpacity={0.45}
            strokeDasharray="4 4"
            label={{
              value: "flag threshold",
              position: "insideTopRight",
              fill: MUTE,
              fontSize: 10,
            }}
          />
          <Line
            type="monotone"
            dataKey="risk"
            stroke={INK}
            strokeOpacity={0.55}
            strokeWidth={1.5}
            isAnimationActive={false}
            dot={({ cx, cy, payload }: { cx?: number; cy?: number; payload?: Point }) =>
              cx != null && cy != null && payload ? (
                <circle
                  key={payload.id}
                  cx={cx}
                  cy={cy}
                  r={payload.verdict === "flagged" ? 4.5 : 3}
                  fill={verdictColor(payload.verdict)}
                  stroke="#000000"
                  strokeWidth={1}
                  style={{ cursor: onPointClick ? "pointer" : undefined }}
                  onClick={() => onPointClick?.(payload.id)}
                />
              ) : (
                <g key={`empty-${cx}-${cy}`} />
              )
            }
            activeDot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
