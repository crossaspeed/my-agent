import { Breadcrumb, Spin, Tabs, Tag, Typography, Result, Button } from 'antd'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { courseApi } from '@/api/endpoints'
import { isTeacher, useAuth } from '@/store/auth'
import DocumentsTab from './DocumentsTab'
import QuestionsTab from './QuestionsTab'
import PapersTab from './PapersTab'
import AnalyticsTab from './AnalyticsTab'

export default function CourseWorkbench() {
  const { courseId } = useParams()
  const id = Number(courseId)
  const navigate = useNavigate()
  const user = useAuth((s) => s.user)
  const teacher = isTeacher(user)

  const { data: course, isLoading, error } = useQuery({
    queryKey: ['course', id],
    queryFn: () => courseApi.detail(id),
    enabled: Number.isFinite(id),
  })

  if (isLoading) {
    return (
      <div className="page" style={{ textAlign: 'center', paddingTop: 120 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (error || !course) {
    return (
      <Result
        status="404"
        title="课程不存在或无权访问"
        extra={
          <Button type="primary" onClick={() => navigate('/courses')}>
            返回课程列表
          </Button>
        }
      />
    )
  }

  const items = [
    {
      key: 'documents',
      label: '课程知识库',
      children: <DocumentsTab courseId={id} canEdit={teacher} />,
    },
    {
      key: 'questions',
      label: teacher ? '题库与审核' : '练习题库',
      children: <QuestionsTab courseId={id} canEdit={teacher} />,
    },
    {
      key: 'papers',
      label: '测评试卷',
      children: <PapersTab courseId={id} canEdit={teacher} />,
    },
    ...(teacher
      ? [{ key: 'analytics', label: '学情分析', children: <AnalyticsTab courseId={id} /> }]
      : []),
  ]

  return (
    <div className="page">
      <Breadcrumb
        items={[{ title: <Link to="/courses">我的课程</Link> }, { title: course.name }]}
        style={{ marginBottom: 8 }}
      />
      <div className="page-head">
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            {course.name}
            <Tag color={course.my_role === 'student' ? 'blue' : 'gold'} style={{ marginLeft: 8 }}>
              {course.my_role === 'student' ? '学生视角' : '教师视角'}
            </Tag>
          </Typography.Title>
          <Typography.Text type="secondary">
            {course.code} · 课件 {course.stats.documents} · 知识点 {course.stats.knowledge_points} · 分块{' '}
            {course.stats.chunks} · 学生 {course.stats.students}
          </Typography.Text>
        </div>
      </div>
      <Tabs items={items} destroyInactiveTabPane />
    </div>
  )
}
