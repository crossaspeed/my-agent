import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Col,
  Input,
  Modal,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Tree,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { errorText } from '@/api/client'
import { courseApi } from '@/api/endpoints'
import type { ErrorHeatCell, Job, KnowledgePoint, Member } from '@/api/types'
import EmptyState from '@/components/EmptyState'

interface Props {
  courseId: number
}

function toTreeData(nodes: KnowledgePoint[]): { key: number; title: string; children?: unknown[] }[] {
  return nodes.map((node) => ({
    key: node.id,
    title: `${node.name}${node.chunk_count ? `（${node.chunk_count} 个分块）` : ''}`,
    children: toTreeData(node.children ?? []),
  }))
}

export default function AnalyticsTab({ courseId }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [memberOpen, setMemberOpen] = useState(false)
  const [kpName, setKpName] = useState('')
  const [memberText, setMemberText] = useState('')

  const { data: overview } = useQuery({
    queryKey: ['overview', courseId],
    queryFn: () => courseApi.overview(courseId),
  })
  const { data: heatmap, isLoading: heatLoading } = useQuery({
    queryKey: ['heatmap', courseId],
    queryFn: () => courseApi.errorHeatmap(courseId),
  })
  const { data: kpTree } = useQuery({
    queryKey: ['kp-tree', courseId],
    queryFn: () => courseApi.kpTree(courseId),
  })
  const { data: members } = useQuery({
    queryKey: ['members', courseId],
    queryFn: () => courseApi.members(courseId),
  })
  const { data: jobs } = useQuery({
    queryKey: ['course-jobs', courseId],
    queryFn: () => courseApi.jobs(courseId),
  })

  const addMemberMutation = useMutation({
    mutationFn: (usernames: string[]) => courseApi.addMembers(courseId, usernames),
    onSuccess: () => {
      message.success('已添加学生')
      setMemberOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['members', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const addKpMutation = useMutation({
    mutationFn: (name: string) => courseApi.createKp(courseId, { name }),
    onSuccess: () => {
      message.success('知识点已添加')
      setKpName('')
      void queryClient.invalidateQueries({ queryKey: ['kp-tree', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const autoKpMutation = useMutation({
    mutationFn: () => courseApi.autoKp(courseId),
    onSuccess: (points) => {
      message.success(`已从课件抽取 ${points.length} 个知识点`)
      void queryClient.invalidateQueries({ queryKey: ['kp-tree', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const heatColumns: ColumnsType<ErrorHeatCell> = [
    { title: '知识点', dataIndex: 'kp_name' },
    { title: '作答次数', dataIndex: 'total', width: 100 },
    { title: '错误次数', dataIndex: 'wrong', width: 100 },
    {
      title: '错误率',
      dataIndex: 'rate',
      width: 200,
      render: (rate: number) => (
        <Progress percent={Math.round((rate ?? 0) * 100)} size="small" status={rate > 0.5 ? 'exception' : 'normal'} />
      ),
    },
    {
      title: '主要错因',
      dataIndex: 'tags',
      render: (tags: Record<string, number>) => (
        <Space wrap size={4}>
          {Object.entries(tags ?? {})
            .sort((a, b) => b[1] - a[1])
            .slice(0, 3)
            .map(([tag, count]) => (
              <Tag key={tag} color="volcano">
                {tag} × {count}
              </Tag>
            ))}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        {[
          { title: '课件', value: overview?.documents ?? 0 },
          { title: '知识分块', value: overview?.chunks ?? 0 },
          { title: '题库', value: overview?.questions ?? 0 },
          { title: '已发布题目', value: overview?.published_questions ?? 0 },
          { title: '测评次数', value: overview?.attempts ?? 0 },
          { title: '平均分', value: overview?.avg_score ?? 0, precision: 1 },
        ].map((item) => (
          <Col key={item.title} xs={12} md={8} xl={4}>
            <Card size="small">
              <Statistic title={item.title} value={item.value} precision={item.precision} valueStyle={{ fontSize: 22 }} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        size="small"
        title="班级错题分布（知识点 × 错因）"
        extra={<Typography.Text type="secondary">数据来自已批阅的主观题要点命中与客观题判错</Typography.Text>}
      >
        <Table<ErrorHeatCell>
          rowKey="kp_id"
          size="small"
          loading={heatLoading}
          columns={heatColumns}
          dataSource={heatmap ?? []}
          pagination={false}
          locale={{ emptyText: <EmptyState description="还没有作答数据，学生完成一次测评后即可看到错题分布" /> }}
        />
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card
            size="small"
            title="知识点树"
            extra={
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                loading={autoKpMutation.isPending}
                onClick={() => autoKpMutation.mutate()}
              >
                从课件自动抽取
              </Button>
            }
          >
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="新增知识点名称"
                  value={kpName}
                  onChange={(e) => setKpName(e.target.value)}
                  onPressEnter={() => kpName.trim() && addKpMutation.mutate(kpName.trim())}
                />
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  loading={addKpMutation.isPending}
                  onClick={() => kpName.trim() && addKpMutation.mutate(kpName.trim())}
                >
                  添加
                </Button>
              </Space.Compact>
              {kpTree?.length ? (
                <Tree showLine defaultExpandAll treeData={toTreeData(kpTree) as never} selectable={false} />
              ) : (
                <EmptyState description="还没有知识点，可一键从课件标题结构抽取" />
              )}
            </Space>
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card
            size="small"
            title={`课程成员（${members?.length ?? 0}）`}
            extra={
              <Button size="small" onClick={() => setMemberOpen(true)}>
                添加学生
              </Button>
            }
          >
            <Table<Member>
              rowKey="user_id"
              size="small"
              pagination={false}
              dataSource={members ?? []}
              columns={[
                { title: '用户名', dataIndex: 'username' },
                { title: '姓名', dataIndex: 'real_name', render: (v: string) => v || '—' },
                {
                  title: '角色',
                  dataIndex: 'role',
                  width: 100,
                  render: (v: string) => <Tag color={v === 'student' ? 'blue' : 'gold'}>{v === 'student' ? '学生' : '教师'}</Tag>,
                },
              ]}
              locale={{ emptyText: <EmptyState description="暂无成员" /> }}
            />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="最近后台任务">
        <Table<Job>
          rowKey="task_id"
          size="small"
          pagination={false}
          dataSource={(jobs ?? []).slice(0, 8)}
          columns={[
            { title: '类型', dataIndex: 'job_type', width: 160 },
            {
              title: '状态',
              dataIndex: 'status',
              width: 110,
              render: (v: string) => (
                <Tag color={v === 'succeeded' ? 'success' : v === 'failed' ? 'error' : 'processing'}>
                  {v === 'succeeded' ? '成功' : v === 'failed' ? '失败' : '进行中'}
                </Tag>
              ),
            },
            {
              title: '进度',
              dataIndex: 'progress',
              width: 200,
              render: (v: number, record) => (
                <Progress percent={v} size="small" status={record.status === 'failed' ? 'exception' : 'normal'} />
              ),
            },
            { title: '阶段', dataIndex: 'stage', render: (v: string) => v || '—' },
          ]}
          locale={{ emptyText: <EmptyState description="暂无任务" /> }}
        />
      </Card>

      <Modal
        title="批量添加学生"
        open={memberOpen}
        onCancel={() => setMemberOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Typography.Paragraph type="secondary">
          每行一个用户名，学生需先自行注册账号（学生角色无需邀请码）。
        </Typography.Paragraph>
        <Input.TextArea
          autoSize={{ minRows: 4 }}
          placeholder={'student1\nstudent2'}
          value={memberText}
          onChange={(e) => setMemberText(e.target.value)}
        />
        <Space style={{ marginTop: 16 }}>
          <Button
            type="primary"
            loading={addMemberMutation.isPending}
            onClick={() => {
              const names = memberText
                .split(/[\s,，]+/)
                .map((item) => item.trim())
                .filter(Boolean)
              if (!names.length) {
                message.warning('请填写至少一个用户名')
                return
              }
              addMemberMutation.mutate(names)
            }}
          >
            添加
          </Button>
        </Space>
      </Modal>
    </Space>
  )
}
