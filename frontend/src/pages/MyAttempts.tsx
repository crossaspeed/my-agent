import { FileTextOutlined } from '@ant-design/icons'
import { Button, Card, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { attemptApi } from '@/api/endpoints'
import type { Attempt } from '@/api/types'
import EmptyState from '@/components/EmptyState'

const STATUS: Record<string, { color: string; text: string }> = {
  in_progress: { color: 'processing', text: '作答中' },
  submitted: { color: 'warning', text: '阅卷中' },
  graded: { color: 'success', text: '已出分' },
}

export default function MyAttemptsPage() {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({ queryKey: ['my-attempts'], queryFn: attemptApi.mine })

  const columns: ColumnsType<Attempt> = [
    {
      title: '试卷',
      dataIndex: 'paper_title',
      render: (title: string, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{title ?? `试卷 #${record.paper_id}`}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            开始于 {record.started_at ? new Date(record.started_at).toLocaleString() : '—'}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: string) => <Tag color={STATUS[value]?.color}>{STATUS[value]?.text ?? value}</Tag>,
    },
    {
      title: '得分',
      width: 140,
      render: (_, record) =>
        record.total_score != null ? (
          <Typography.Text strong>
            {record.total_score.toFixed(1)} / {record.max_score ?? '—'}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: '操作',
      width: 160,
      render: (_, record) => (
        <Button
          size="small"
          icon={<FileTextOutlined />}
          onClick={() => navigate(record.status === 'in_progress' ? `/exam/${record.id}` : `/report/${record.id}`)}
        >
          {record.status === 'in_progress' ? '继续作答' : '查看报告'}
        </Button>
      ),
    },
  ]

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            我的测评
          </Typography.Title>
          <Typography.Text type="secondary">查看历次测评成绩、逐题解析与知识点掌握度</Typography.Text>
        </div>
      </div>
      <Card size="small">
        <Table<Attempt>
          rowKey="id"
          loading={isLoading}
          columns={columns}
          dataSource={data ?? []}
          pagination={false}
          locale={{ emptyText: <EmptyState description="还没有测评记录，去课程里选择一份已发布试卷开始作答" /> }}
        />
      </Card>
    </div>
  )
}
