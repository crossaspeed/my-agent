import {
  BookOutlined,
  BulbOutlined,
  DashboardOutlined,
  HistoryOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Avatar, Dropdown, Layout, Menu, Space, Tag, Typography } from 'antd'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/store/auth'

const { Header, Sider, Content } = Layout

const ROLE_LABEL: Record<string, string> = { admin: '管理员', teacher: '教师', student: '学生' }

export default function AppLayout() {
  const user = useAuth((s) => s.user)
  const logout = useAuth((s) => s.logout)
  const navigate = useNavigate()
  const location = useLocation()

  const selected = location.pathname.startsWith('/courses')
    ? '/courses'
    : location.pathname.startsWith('/tutor')
      ? '/tutor'
      : location.pathname.startsWith('/attempts')
        ? '/attempts'
        : '/courses'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="light" width={216} breakpoint="lg" collapsedWidth={64} style={{ borderRight: '1px solid #f0f0f0' }}>
        <div className="brand">
          <span className="brand-mark">智</span>
          <div className="brand-text">
            <Typography.Text strong>智评导学</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              多智能体自主测评
            </Typography.Text>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selected]}
          style={{ borderInlineEnd: 'none' }}
          items={[
            { key: '/courses', icon: <BookOutlined />, label: <Link to="/courses">我的课程</Link> },
            { key: '/attempts', icon: <HistoryOutlined />, label: <Link to="/attempts">我的测评</Link> },
            { key: '/tutor', icon: <BulbOutlined />, label: <Link to="/tutor">AI 导学</Link> },
          ]}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <Space size={8}>
            <DashboardOutlined style={{ color: '#1677ff' }} />
            <Typography.Text strong>面向课程知识库的多智能体自主测评与导学系统</Typography.Text>
          </Space>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  onClick: () => {
                    logout()
                    navigate('/login', { replace: true })
                  },
                },
              ],
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} style={{ background: '#1677ff' }} />
              <span>{user?.real_name || user?.username}</span>
              <Tag color={user?.role === 'student' ? 'blue' : 'gold'}>{ROLE_LABEL[user?.role ?? ''] ?? user?.role}</Tag>
            </Space>
          </Dropdown>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
