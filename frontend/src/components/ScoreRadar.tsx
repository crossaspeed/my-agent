import { Empty, Typography } from 'antd'

interface Props {
  data: { name: string; rate: number }[]
  size?: number
  caption?: string
}

const CX = 180
const CY = 150
const R = 108

function point(index: number, total: number, ratio: number) {
  const angle = (Math.PI * 2 * index) / total - Math.PI / 2
  return [CX + Math.cos(angle) * R * ratio, CY + Math.sin(angle) * R * ratio] as const
}

/** 知识点掌握度雷达（纯 SVG，避免引入图表库） */
export default function ScoreRadar({ data, size = 360, caption }: Props) {
  if (!data.length) {
    return <Empty description="暂无知识点掌握数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }
  const total = data.length
  const rings = [0.25, 0.5, 0.75, 1]
  const polygon = data
    .map((item, i) => point(i, total, Math.max(0.04, Math.min(1, item.rate))).join(','))
    .join(' ')

  return (
    <div style={{ textAlign: 'center' }}>
      <svg viewBox="0 0 360 300" width={size} height={(size * 300) / 360} role="img">
        {rings.map((ring) => (
          <polygon
            key={ring}
            points={data.map((_, i) => point(i, total, ring).join(',')).join(' ')}
            fill={ring === 1 ? 'rgba(22,119,255,0.03)' : 'none'}
            stroke="#e5e7eb"
            strokeWidth={1}
          />
        ))}
        {data.map((item, i) => {
          const [x, y] = point(i, total, 1)
          return <line key={item.name} x1={CX} y1={CY} x2={x} y2={y} stroke="#e5e7eb" strokeWidth={1} />
        })}
        <polygon points={polygon} fill="rgba(22,119,255,0.25)" stroke="#1677ff" strokeWidth={2} />
        {data.map((item, i) => {
          const [x, y] = point(i, total, Math.max(0.04, Math.min(1, item.rate)))
          return <circle key={`${item.name}-dot`} cx={x} cy={y} r={3} fill="#1677ff" />
        })}
        {data.map((item, i) => {
          const [x, y] = point(i, total, 1.16)
          const anchor = x > CX + 12 ? 'start' : x < CX - 12 ? 'end' : 'middle'
          const short = item.name.length > 10 ? `${item.name.slice(0, 9)}…` : item.name
          return (
            <text key={`${item.name}-label`} x={x} y={y} textAnchor={anchor} fontSize={11} fill="#595959">
              {short} {Math.round(item.rate * 100)}%
            </text>
          )
        })}
      </svg>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {caption ?? '掌握度 = 该知识点得分率（按 100% 归一）'}
      </Typography.Text>
    </div>
  )
}
