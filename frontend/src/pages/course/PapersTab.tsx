import { FileDoneOutlined, PlayCircleOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Col,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { errorText } from '@/api/client'
import { attemptApi, courseApi, paperApi } from '@/api/endpoints'
import type { KnowledgePoint, PaperListItem } from '@/api/types'
import EmptyState from '@/components/EmptyState'

interface Props {
  courseId: number
  canEdit: boolean
}

interface CreatePaperForm {
  title: string
  description?: string
  kp_ids: number[]
  types: string[]
  counts: Record<string, number>
  duration_min: number
  total_score: number
}

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  published: { color: 'success', text: '已发布' },
  closed: { color: 'default', text: '已结束' },
}

const ATTEMPT_TAG: Record<string, { color: string; text: string }> = {
  in_progress: { color: 'processing', text: '作答中' },
  submitted: { color: 'warning', text: '阅卷中' },
  graded: { color: 'success', text: '已出分' },
}

const TYPE_LABEL: Record<string, string> = {
  single: '单选',
  multiple: '多选',
  judge: '判断',
  short: '简答',
  essay: '论述',
}

function flattenKps(nodes: KnowledgePoint[], depth = 0): { value: number; label: string }[] {
  return nodes.flatMap((node) => [
    { value: node.id, label: `${'　'.repeat(depth)}${node.name}` },
    ...flattenKps(node.children ?? [], depth + 1),
  ])
}

export default function PapersTab({ courseId, canEdit }: Props) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [statsPaper, setStatsPaper] = useState<PaperListItem | null>(null)
  const [form] = Form.useForm<CreatePaperForm>()

  const { data: papers, isLoading } = useQuery({
    queryKey: ['papers', courseId],
    queryFn: () => paperApi.list(courseId),
  })
  const { data: kpTree } = useQuery({
    queryKey: ['kp-tree', courseId],
    queryFn: () => courseApi.kpTree(courseId),
  })
  const kpOptions = useMemo(() => flattenKps(kpTree ?? []), [kpTree])

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['paper-stats', statsPaper?.id],
    queryFn: () => paperApi.stats(statsPaper!.id),
    enabled: Boolean(statsPaper),
  })

  const createMutation = useMutation({
    mutationFn: (values: CreatePaperForm) => {
      const types: Record<string, number> = {}
      for (const key of values.types) types[key] = values.counts?.[key] ?? 1
      return paperApi.create({
        course_id: courseId,
        title: values.title,
        description: values.description,
        mode: 'auto',
        config: { kp_ids: values.kp_ids ?? [], types },
        duration_min: values.duration_min,
        total_score: values.total_score,
      })
    },
    onSuccess: (paper) => {
      message.success(`试卷已生成（${paper.questions.length} 题 / ${paper.total_score} 分），发布后学生即可作答`)
      setOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['papers', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const publishMutation = useMutation({
    mutationFn: (id: number) => paperApi.publish(id),
    onSuccess: () => {
      message.success('试卷已发布')
      void queryClient.invalidateQueries({ queryKey: ['papers', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const startMutation = useMutation({
    mutationFn: (paperId: number) => attemptApi.start(paperId),
    onSuccess: (attempt) => navigate(`/exam/${attempt.id}`),
    onError: (error) => message.error(errorText(error)),
  })

  const baseColumns: ColumnsType<PaperListItem> = [
    {
      title: '试卷',
      dataIndex: 'title',
      render: (title: string, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{title}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {record.question_count} 题 · {record.total_score} 分 · {record.duration_min} 分钟
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => <Tag color={STATUS_TAG[value]?.color}>{STATUS_TAG[value]?.text ?? value}</Tag>,
    },
  ]

  const teacherColumns: ColumnsType<PaperListItem> = [
    {
      title: '已提交',
      width: 100,
      render: (_, record) => <Typography.Text>{record.attempt_status ? '有' : '—'}</Typography.Text>,
    },
    {
      title: '操作',
      width: 240,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => setStatsPaper(record)}>
            班级成绩
          </Button>
          {record.status === 'draft' && (
            <Button
              size="small"
              type="primary"
              ghost
              icon={<SendOutlined />}
              loading={publishMutation.isPending}
              onClick={() => publishMutation.mutate(record.id)}
            >
              发布
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const studentColumns: ColumnsType<PaperListItem> = [
    {
      title: '我的成绩',
      width: 120,
      render: (_, record) =>
        typeof record.my_score === 'number' ? (
          <Typography.Text strong>{record.my_score.toFixed(1)} 分</Typography.Text>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: '操作',
      width: 170,
      render: (_, record) => {
        const status = record.attempt_status
        if (record.status !== 'published' && !record.attempt_id) {
          return <Tag>未发布</Tag>
        }
        if (status === 'graded') {
          return (
            <Button
              size="small"
              icon={<FileDoneOutlined />}
              onClick={() => navigate(`/report/${record.attempt_id}`)}
            >
              查看报告
            </Button>
          )
        }
        if (status === 'submitted') {
          return <Tag color={ATTEMPT_TAG.submitted.color}>阅卷中</Tag>
        }
        return (
          <Button
            size="small"
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={startMutation.isPending}
            onClick={() => {
              if (record.attempt_id) {
                navigate(`/exam/${record.attempt_id}`)
                return
              }
              startMutation.mutate(record.id)
            }}
          >
            {status === 'in_progress' ? '继续作答' : '开始测评'}
          </Button>
        )
      },
    },
  ]

  const columns: ColumnsType<PaperListItem> = [
    ...baseColumns,
    ...(canEdit ? teacherColumns : studentColumns),
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {canEdit && (
        <Card size="small">
          <Row align="middle" gutter={12}>
            <Col flex="auto">
              <Space size={24} wrap>
                <Statistic title="试卷总数" value={papers?.length ?? 0} valueStyle={{ fontSize: 20 }} />
                <Statistic
                  title="已发布"
                  value={(papers ?? []).filter((p) => p.status === 'published').length}
                  valueStyle={{ fontSize: 20 }}
                />
              </Space>
            </Col>
            <Col>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
                组卷
              </Button>
            </Col>
          </Row>
        </Card>
      )}

      <Table<PaperListItem>
        rowKey="id"
        size="middle"
        loading={isLoading}
        columns={columns}
        dataSource={papers ?? []}
        pagination={false}
        locale={{
          emptyText: (
            <EmptyState description={canEdit ? '还没有试卷，按知识点自动组卷试试' : '教师还没有发布测评试卷'} />
          ),
        }}
      />

      <Drawer
        title={`班级成绩 · ${statsPaper?.title ?? ''}`}
        width={620}
        open={Boolean(statsPaper)}
        onClose={() => setStatsPaper(null)}
      >
        {stats && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Row gutter={16}>
              <Col span={6}>
                <Statistic title="提交人数" value={stats.submitted} />
              </Col>
              <Col span={6}>
                <Statistic title="平均分" value={stats.avg_score} precision={1} />
              </Col>
              <Col span={6}>
                <Statistic title="最高分" value={stats.max_score} precision={1} />
              </Col>
              <Col span={6}>
                <Statistic title="最低分" value={stats.min_score} precision={1} />
              </Col>
            </Row>
            <Table
              size="small"
              rowKey={(row) => String(row.student_id ?? row.username ?? Math.random())}
              loading={statsLoading}
              dataSource={stats.items}
              pagination={false}
              columns={[
                { title: '学生', dataIndex: 'username', render: (v: string) => v ?? '—' },
                {
                  title: '得分',
                  dataIndex: 'total_score',
                  width: 100,
                  render: (v: number | undefined) => (typeof v === 'number' ? v.toFixed(1) : '—'),
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 110,
                  render: (v: string) => {
                    const tag = ATTEMPT_TAG[v]
                    return <Tag color={tag?.color}>{tag?.text ?? v}</Tag>
                  },
                },
              ]}
            />
          </Space>
        )}
      </Drawer>

      <Modal
        title="自动组卷"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={createMutation.isPending}
        okText="生成试卷"
        width={600}
      >
        <Form<CreatePaperForm>
          form={form}
          layout="vertical"
          initialValues={{
            types: ['single', 'short'],
            counts: { single: 5, multiple: 2, judge: 3, short: 2, essay: 1 },
            duration_min: 45,
            total_score: 100,
            kp_ids: [],
          }}
          onFinish={(values) => createMutation.mutate(values)}
        >
          <Form.Item name="title" label="试卷标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="如《计算机网络》传输层阶段测评" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea autoSize={{ minRows: 2 }} placeholder="选填" />
          </Form.Item>
          <Form.Item name="kp_ids" label="知识点范围（留空=全课程，系统尽量覆盖所选知识点）">
            <Select mode="multiple" allowClear options={kpOptions} />
          </Form.Item>
          <Form.Item name="types" label="题型">
            <Select mode="multiple" options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item shouldUpdate noStyle>
            {({ getFieldValue }) => {
              const types = (getFieldValue('types') as string[]) ?? []
              return (
                <Row gutter={12}>
                  {types.map((key) => (
                    <Col span={8} key={key}>
                      <Form.Item name={['counts', key]} label={`${TYPE_LABEL[key]} 数量`}>
                        <InputNumber min={1} max={20} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                  ))}
                </Row>
              )
            }}
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="duration_min" label="时长（分钟）">
                <InputNumber min={5} max={300} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="total_score" label="总分">
                <InputNumber min={10} max={1000} step={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </Space>
  )
}
