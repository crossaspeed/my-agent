import { ClockCircleOutlined } from '@ant-design/icons'
import { Tag, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'

interface Props {
  startedAt?: string | null
  durationMin: number
  /** 已交卷/已结束则暂停计时 */
  paused?: boolean
  onExpire?: () => void
}

function format(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(sec).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

/** 考试倒计时：以服务端 started_at 为准，刷新页面不丢时间；到点自动交卷 */
export default function ExamTimer({ startedAt, durationMin, paused, onExpire }: Props) {
  const deadline = useMemo(() => {
    const base = startedAt ? new Date(startedAt).getTime() : Date.now()
    return base + durationMin * 60_000
  }, [startedAt, durationMin])

  const [remain, setRemain] = useState(() => (deadline - Date.now()) / 1000)
  const firedRef = useRef(false)

  useEffect(() => {
    firedRef.current = false
    setRemain((deadline - Date.now()) / 1000)
  }, [deadline])

  useEffect(() => {
    if (paused) return
    const timer = window.setInterval(() => {
      const left = (deadline - Date.now()) / 1000
      setRemain(left)
      if (left <= 0 && !firedRef.current) {
        firedRef.current = true
        onExpire?.()
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [deadline, paused, onExpire])

  const danger = remain <= 300
  return (
    <Tag color={danger ? 'red' : 'blue'} style={{ fontSize: 15, padding: '4px 10px' }}>
      <ClockCircleOutlined /> 剩余 <Typography.Text strong style={{ color: danger ? '#cf1322' : '#1677ff' }}>{format(remain)}</Typography.Text>
    </Tag>
  )
}
