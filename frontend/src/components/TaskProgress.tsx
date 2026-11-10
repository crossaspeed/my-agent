import { Alert, Progress, Space, Typography } from 'antd'
import { useEffect, useRef } from 'react'
import { useJobPolling } from '@/hooks/useJobPolling'
import type { Job } from '@/api/types'

interface Props {
  taskId?: string | null
  /** 任务成功后回调（只触发一次） */
  onDone?: (job: Job) => void
  onFail?: (job: Job) => void
  title?: string
}

/** 任务进度条：解析/出题/阅卷统一交互（轮询 /jobs/{task_id}） */
export default function TaskProgress({ taskId, onDone, onFail, title }: Props) {
  const { data: job, error } = useJobPolling(taskId)
  const firedRef = useRef<string | null>(null)

  useEffect(() => {
    if (!job) return
    if (firedRef.current === job.task_id) return
    if (job.status === 'succeeded') {
      firedRef.current = job.task_id
      onDone?.(job)
    } else if (job.status === 'failed') {
      firedRef.current = job.task_id
      onFail?.(job)
    }
  }, [job, onDone, onFail])

  if (!taskId) return null

  if (error) {
    return <Alert type="error" showIcon message="任务状态查询失败" description={(error as Error).message} />
  }

  const status = job?.status ?? 'pending'
  const failed = status === 'failed'
  const percent = failed ? 100 : Math.max(job?.progress ?? 0, 1)

  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Text type="secondary">
          {title ?? '后台任务'}：{job?.stage ?? (job ? statusText(status) : '已提交…')}
        </Typography.Text>
        <Typography.Text type={failed ? 'danger' : 'secondary'}>
          {failed ? '失败' : `${percent}%`}
        </Typography.Text>
      </Space>
      <Progress
        percent={percent}
        size="small"
        status={failed ? 'exception' : status === 'succeeded' ? 'success' : 'active'}
        showInfo={false}
      />
      {failed && job?.error_msg && (
        <Alert type="error" showIcon message={job.error_msg} style={{ marginTop: 8 }} />
      )}
    </Space>
  )
}

function statusText(status: string): string {
  switch (status) {
    case 'pending':
      return '排队中…'
    case 'running':
      return '处理中…'
    case 'succeeded':
      return '已完成'
    case 'failed':
      return '失败'
    default:
      return status
  }
}
