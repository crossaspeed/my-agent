import { CheckOutlined, CloseOutlined, EditOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  Alert,
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
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { errorText } from '@/api/client'
import { courseApi, questionApi } from '@/api/endpoints'
import type { KnowledgePoint, Question, SourceRef } from '@/api/types'
import EmptyState from '@/components/EmptyState'
import QuestionEditor, { type QuestionPatch } from '@/components/QuestionEditor'
import SourceDrawer from '@/components/SourceDrawer'
import TaskProgress from '@/components/TaskProgress'

interface Props {
  courseId: number
  canEdit: boolean
}

interface GenerateForm {
  types: string[]
  counts: Record<string, number>
  kp_ids: number[]
  difficulty: number
  requirements?: string
  auto_publish: boolean
}

const TYPE_LABEL: Record<string, string> = {
  single: '单选',
  multiple: '多选',
  judge: '判断',
  short: '简答',
  essay: '论述',
}

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  pending: { color: 'processing', text: '待审核' },
  published: { color: 'success', text: '已发布' },
  rejected: { color: 'error', text: '已驳回' },
  archived: { color: 'default', text: '已归档' },
}

function flattenKps(nodes: KnowledgePoint[], depth = 0): { value: number; label: string }[] {
  return nodes.flatMap((node) => [
    { value: node.id, label: `${'　'.repeat(depth)}${node.name}` },
    ...flattenKps(node.children ?? [], depth + 1),
  ])
}

export default function QuestionsTab({ courseId, canEdit }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<string | undefined>(canEdit ? 'pending' : 'published')
  const [type, setType] = useState<string | undefined>()
  const [genOpen, setGenOpen] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [editing, setEditing] = useState<Question | null>(null)
  const [refs, setRefs] = useState<SourceRef[] | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [form] = Form.useForm<GenerateForm>()

  const { data: kpTree } = useQuery({
    queryKey: ['kp-tree', courseId],
    queryFn: () => courseApi.kpTree(courseId),
  })
  const kpOptions = useMemo(() => flattenKps(kpTree ?? []), [kpTree])

  const { data, isLoading } = useQuery({
    queryKey: ['questions', courseId, page, status, type],
    queryFn: () => questionApi.list(courseId, { page, size: 10, status, type }),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['questions', courseId] })
    void queryClient.invalidateQueries({ queryKey: ['course', courseId] })
    setSelected([])
  }

  const generateMutation = useMutation({
    mutationFn: (values: GenerateForm) => {
      const types: Record<string, number> = {}
      for (const key of values.types) types[key] = values.counts?.[key] ?? 1
      const diff = values.difficulty
      return questionApi.generate(courseId, {
        course_id: courseId,
        kp_ids: values.kp_ids ?? [],
        types,
        // 难度倾向 1-5 → easy/medium/hard 权重（后端按权重抽样难度）
        difficulty: { easy: Math.max(0, 5 - diff) / 4, medium: 0.5, hard: Math.max(0, diff - 1) / 4 },
        requirements: values.requirements,
        auto_publish: values.auto_publish,
      })
    },
    onSuccess: (result) => {
      message.success('已提交出题任务，出题官正在检索课件并生成题目')
      setGenOpen(false)
      setJobId(result.job_id)
    },
    onError: (error) => message.error(errorText(error)),
  })

  const reviewMutation = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'approve' | 'reject' }) =>
      questionApi.review(id, action),
    onSuccess: () => {
      message.success('审核已提交')
      invalidate()
    },
    onError: (error) => message.error(errorText(error)),
  })

  const batchMutation = useMutation({
    mutationFn: (action: 'approve' | 'reject') => questionApi.batchReview(selected, action),
    onSuccess: (result, action) => {
      message.success(`已${action === 'approve' ? '通过' : '驳回'} ${result.updated ?? selected.length} 道题`)
      invalidate()
    },
    onError: (error) => message.error(errorText(error)),
  })

  const saveMutation = useMutation({
    mutationFn: (patch: QuestionPatch) => questionApi.update(editing!.id, patch),
    onSuccess: () => {
      message.success('题目已更新')
      setEditing(null)
      invalidate()
    },
    onError: (error) => message.error(errorText(error)),
  })

  const archiveMutation = useMutation({
    mutationFn: (id: number) => questionApi.remove(id),
    onSuccess: () => {
      message.success('题目已归档')
      invalidate()
    },
    onError: (error) => message.error(errorText(error)),
  })

  const columns: ColumnsType<Question> = [
    {
      title: '题干',
      dataIndex: 'stem',
      render: (stem: string, record) => (
        <Space direction="vertical" size={2} style={{ maxWidth: 520 }}>
          <Typography.Text ellipsis={{ tooltip: stem }} style={{ maxWidth: 520 }}>
            {stem}
          </Typography.Text>
          <Space size={4} wrap>
            <Tag>{TYPE_LABEL[record.type] ?? record.type}</Tag>
            <Tag>难度 {record.difficulty}</Tag>
            {record.kp_ids?.length > 0 && <Tag color="cyan">{record.kp_ids.length} 个知识点</Tag>}
          </Space>
        </Space>
      ),
    },
    {
      title: '溯源',
      width: 150,
      render: (_, record) => {
        const quality = record.quality
        const ok = quality?.citation_ok !== false
        const ratio = quality?.quote_match_ratio
        return (
          <Tooltip title={ok ? 'chunk_id 合法且引文与原文一致' : '引文校验未通过，建议人工复核'}>
            <Button
              size="small"
              type="link"
              icon={<SafetyCertificateOutlined />}
              onClick={() => setRefs(record.source_refs ?? [])}
            >
              {record.source_refs?.length ?? 0} 条
              {ratio !== undefined && ` · ${ratio.toFixed(2)}`}
              {!ok && ' ⚠'}
            </Button>
          </Tooltip>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => <Tag color={STATUS_TAG[value]?.color}>{STATUS_TAG[value]?.text ?? value}</Tag>,
    },
    {
      title: '操作',
      width: 250,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => setEditing(record)}>
            编辑
          </Button>
          {canEdit && record.status !== 'published' && (
            <Button
              size="small"
              type="primary"
              ghost
              icon={<CheckOutlined />}
              loading={reviewMutation.isPending}
              onClick={() => reviewMutation.mutate({ id: record.id, action: 'approve' })}
            >
              通过
            </Button>
          )}
          {canEdit && record.status !== 'rejected' && (
            <Button
              size="small"
              danger
              icon={<CloseOutlined />}
              onClick={() => reviewMutation.mutate({ id: record.id, action: 'reject' })}
            >
              驳回
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small">
        <Row gutter={12} align="middle">
          <Col flex="auto">
            <Space wrap>
              <Select
                allowClear
                placeholder="题目状态"
                style={{ width: 140 }}
                value={status}
                onChange={(value) => {
                  setStatus(value)
                  setPage(1)
                }}
                options={Object.entries(STATUS_TAG).map(([value, item]) => ({ value, label: item.text }))}
              />
              <Select
                allowClear
                placeholder="题型"
                style={{ width: 120 }}
                value={type}
                onChange={(value) => {
                  setType(value)
                  setPage(1)
                }}
                options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))}
              />
              <Typography.Text type="secondary">共 {data?.total ?? 0} 道</Typography.Text>
            </Space>
          </Col>
          <Col>
            <Space>
              {canEdit && selected.length > 0 && (
                <>
                  <Button
                    type="primary"
                    ghost
                    loading={batchMutation.isPending}
                    onClick={() => batchMutation.mutate('approve')}
                  >
                    批量通过（{selected.length}）
                  </Button>
                  <Button danger onClick={() => batchMutation.mutate('reject')}>
                    批量驳回
                  </Button>
                </>
              )}
              {canEdit && (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setGenOpen(true)}>
                  AI 出题
                </Button>
              )}
            </Space>
          </Col>
        </Row>
      </Card>

      <TaskProgress
        taskId={jobId}
        title="智能出题"
        onDone={(job) => {
          const result = job.result as { created?: number; rejected?: number } | null
          message.success(`出题完成：生成 ${result?.created ?? 0} 道，引用校验淘汰 ${result?.rejected ?? 0} 道`)
          invalidate()
        }}
      />

      <Table<Question>
        rowKey="id"
        size="middle"
        loading={isLoading}
        columns={columns}
        dataSource={data?.items ?? []}
        rowSelection={
          canEdit
            ? {
                selectedRowKeys: selected,
                onChange: (keys) => setSelected(keys as number[]),
                getCheckboxProps: (record) => ({ disabled: record.status === 'published' }),
              }
            : undefined
        }
        pagination={{
          current: page,
          total: data?.total ?? 0,
          pageSize: 10,
          onChange: setPage,
          showSizeChanger: false,
        }}
        locale={{ emptyText: <EmptyState description="还没有题目，用 AI 出题从课件中生成" /> }}
        expandable={{
          expandedRowRender: (record) => (
            <Space direction="vertical" size={6} style={{ width: '100%' }}>
              {record.options && record.options.length > 0 && (
                <Space direction="vertical" size={2}>
                  {record.options.map((option) => (
                    <Typography.Text key={option.key}>
                      {option.key}. {option.text}
                    </Typography.Text>
                  ))}
                </Space>
              )}
              <Typography.Text type="secondary">
                参考答案：{JSON.stringify(record.answer)}
              </Typography.Text>
              {record.rubric?.length > 0 && (
                <Typography.Text type="secondary">
                  评分要点：{record.rubric.map((r) => `${r.point}(${r.score}分)`).join('；')}
                </Typography.Text>
              )}
              {record.explanation && (
                <Typography.Paragraph style={{ marginBottom: 0 }} type="secondary">
                  解析：{record.explanation}
                </Typography.Paragraph>
              )}
              <Space>
                <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => setRefs(record.source_refs ?? [])}>
                  查看溯源
                </Button>
                <Button size="small" danger onClick={() => archiveMutation.mutate(record.id)}>
                  归档
                </Button>
              </Space>
            </Space>
          ),
        }}
      />

      <SourceDrawer open={refs !== null} refs={refs ?? []} onClose={() => setRefs(null)} />

      <Modal
        title="AI 出题"
        open={genOpen}
        onCancel={() => setGenOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={generateMutation.isPending}
        okText="开始生成"
        width={560}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="出题官会先检索指定知识点下的课件原文，再生成题目并逐题校验引用溯源；未通过校验的题目会被自动丢弃。"
        />
        <Form<GenerateForm>
          form={form}
          layout="vertical"
          initialValues={{ types: ['single', 'short'], counts: { single: 3, multiple: 1, judge: 1, short: 2, essay: 1 }, difficulty: 3, auto_publish: false }}
          onFinish={(values) => generateMutation.mutate(values)}
        >
          <Form.Item name="types" label="题型" rules={[{ required: true, message: '至少选择一种题型' }]}>
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
                        <InputNumber min={1} max={10} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                  ))}
                </Row>
              )
            }}
          </Form.Item>
          <Form.Item name="kp_ids" label="知识点范围（留空=全课程）">
            <Select mode="multiple" allowClear options={kpOptions} placeholder="选择知识点" />
          </Form.Item>
          <Form.Item name="difficulty" label="难度倾向（1 易 - 5 难）">
            <InputNumber min={1} max={5} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="requirements" label="附加要求">
            <Input.TextArea autoSize={{ minRows: 2 }} placeholder="如：侧重三次握手与拥塞控制的对比" />
          </Form.Item>
          <Form.Item name="auto_publish" label="生成后自动发布（跳过人工审核）" valuePropName="checked">
            <Select
              options={[
                { value: false, label: '否，进入待审核队列' },
                { value: true, label: '是，直接发布' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title="编辑题目"
        width={760}
        open={editing !== null}
        onClose={() => setEditing(null)}
        destroyOnClose
      >
        {editing && (
          <QuestionEditor
            question={editing}
            saving={saveMutation.isPending}
            onSubmit={(patch) => saveMutation.mutate(patch)}
            onCancel={() => setEditing(null)}
          />
        )}
      </Drawer>
    </Space>
  )
}
