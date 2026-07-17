import { PolarAngleAxis, RadialBar, RadialBarChart } from "recharts"

/*
 * Threat scoring gauge — §4 threat-state mapping on the design tokens:
 * clean = accent-green, investigating band = accent-orange, flagged =
 * accent-red. The track is a hairline-strength white; the value arc is
 * the accent at full stroke but thin — glow washes stay in the wrapper,
 * never solid fills over surfaces.
 */

const ACCENTS = {
  green: "#11ff99",
  orange: "#ff801f",
  red: "#ff2047",
} as const

export function riskTone(risk: number, threshold: number): keyof typeof ACCENTS {
  if (risk >= threshold) return "red"
  if (risk >= 0.15) return "orange" // the scheduler's material-change band
  return "green"
}

export function RiskGauge({
  risk,
  threshold,
  size = 148,
  label = "Fused risk",
}: {
  risk: number
  threshold: number
  size?: number
  label?: string
}) {
  const tone = riskTone(risk, threshold)
  const color = ACCENTS[tone]
  const pct = Math.round(risk * 100)

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <RadialBarChart
        width={size}
        height={size}
        cx="50%"
        cy="50%"
        innerRadius="78%"
        outerRadius="94%"
        barSize={7}
        data={[{ value: pct }]}
        startAngle={225}
        endAngle={-45}
      >
        <PolarAngleAxis type="number" domain={[0, 100]} tick={false} axisLine={false} />
        <RadialBar
          background={{ fill: "rgba(255,255,255,0.06)" }}
          dataKey="value"
          cornerRadius={4}
          fill={color}
          isAnimationActive={false}
        />
      </RadialBarChart>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-heading-md" style={{ color }}>
          {pct}%
        </span>
        <span className="text-caption text-mute">{label}</span>
      </div>
    </div>
  )
}
