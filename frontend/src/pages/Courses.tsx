import { DeleteOutlined, PlusOutlined, TeamOutlined } from '@ant-design/icons'
import { App, Button, Card, Col, Form, Input, Modal, Popconfirm, Row, Space, Statistic, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { errorText } from '@/api/client'
import { courseApi } from '@/api/endpoints'
import EmptyState from '@/components/EmptyState'
import SkeletonCards from '@/components/SkeletonCards'
import { isTeacher, useAuth } from '@/store/auth'

interface CreateForm {
  code: string
  name: string
  description?: string
}

const ROLE_TAG: Record<string, { color: string; text: string }> = {
  owner: { color: 'gold', text: '创建者' },
  teacher: { color: 'gold', text: '教师' },
  student: { color: 'blue', text: '学生' },
}

export default function CoursesPage() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useAuth((s) => s.user)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm<CreateForm>()

  const { data: courses, isLoading } = useQuery({ queryKey: ['courses'], queryFn: courseApi.list })

  const createMutation = useMutation({
    mutationFn: (values: CreateForm) => courseApi.create(values),
    onSuccess: (course) => {
      message.success('课程已创建')
      setOpen(false)
      form.resetFields()
      void queryClient.invalidateQueries({ queryKey: ['courses'] })
      navigate(`/courses/${course.id}`)
    },
    onError: (error) => message.error(errorText(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => courseApi.remove(id),
    onSuccess: () => {
      message.success('课程已删除')
      void queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            我的课程
          </Typography.Title>
          <Typography.Text type="secondary">
            教师可上传课件、生成并审核题目、组卷发布；学生可参加测评并获得学情报告与 AI 导学
          </Typography.Text>
        </div>
        {isTeacher(user) && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            创建课程
          </Button>
        )}
      </div>

      {isLoading ? (
        <SkeletonCards count={3} />
      ) : !courses?.length ? (
        <EmptyState
          description={isTeacher(user) ? '还没有课程，先创建一门课程并上传课件' : '还没有加入课程，请联系教师添加'}
          action={
            isTeacher(user) ? (
              <Button type="primary" onClick={() => setOpen(true)}>
                创建课程
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Row gutter={[16, 16]}>
          {courses.map((course) => (
            <Col key={course.id} xs={24} md={12} xl={8}>
              <Card
                hoverable
                className="course-card"
                onClick={() => navigate(`/courses/${course.id}`)}
                title={
                  <Space>
                    <span>{course.name}</span>
                    <Tag color={ROLE_TAG[course.my_role]?.color}>{ROLE_TAG[course.my_role]?.text ?? course.my_role}</Tag>
                  </Space>
                }
                extra={
                  <Space size={2} onClick={(event) => event.stopPropagation()}>
                    <Typography.Text type="secondary">{course.code}</Typography.Text>
                    {course.my_role === 'owner' && (
                      <Popconfirm
                        title={`删除课程「${course.name}」？`}
                        description="将同时删除该课程的全部课件、知识点、题目、试卷与作答记录，不可恢复。"
                        okText="确认删除"
                        okButtonProps={{ danger: true }}
                        cancelText="取消"
                        onConfirm={() => deleteMutation.mutate(course.id)}
                      >
                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          loading={deleteMutation.isPending && deleteMutation.variables === course.id}
                          title="删除课程"
                        />
                      </Popconfirm>
                    )}
                  </Space>
                }
              >
                <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ minHeight: 44 }}>
                  {course.description || '暂无课程简介'}
                </Typography.Paragraph>
                <Row gutter={8}>
                  <Col span={6}>
                    <Statistic title="课件" value={course.stats.documents} valueStyle={{ fontSize: 18 }} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="题目" value={course.stats.questions} valueStyle={{ fontSize: 18 }} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="试卷" value={course.stats.papers} valueStyle={{ fontSize: 18 }} />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="学生"
                      value={course.stats.students}
                      prefix={<TeamOutlined />}
                      valueStyle={{ fontSize: 18 }}
                    />
                  </Col>
                </Row>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title="创建课程"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={createMutation.isPending}
        okText="创建"
      >
        <Form<CreateForm> form={form} layout="vertical" onFinish={(values) => createMutation.mutate(values)}>
          <Form.Item name="code" label="课程代码" rules={[{ required: true, min: 2, message: '至少 2 个字符' }]}>
            <Input placeholder="如 CS-NET-01" />
          </Form.Item>
          <Form.Item name="name" label="课程名称" rules={[{ required: true, message: '请输入课程名称' }]}>
            <Input placeholder="如 计算机网络" />
          </Form.Item>
          <Form.Item name="description" label="课程简介">
            <Input.TextArea autoSize={{ minRows: 3 }} placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
