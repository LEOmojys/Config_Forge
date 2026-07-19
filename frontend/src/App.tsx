import { useEffect, useState } from 'react'
import { NavLink, Navigate, useLocation } from 'react-router-dom'
import { Layout, Menu } from 'antd'
import { ExperimentOutlined, TableOutlined, HistoryOutlined, BarChartOutlined } from '@ant-design/icons'
import Workbench from './pages/Workbench'
import Tables from './pages/Tables'
import Traces from './pages/Traces'
import Evaluation from './pages/Evaluation'

const { Header, Sider, Content } = Layout

const navItems = [
  { key: '/', icon: <ExperimentOutlined />, label: 'Workbench' },
  { key: '/tables', icon: <TableOutlined />, label: 'Tables' },
  { key: '/traces', icon: <HistoryOutlined />, label: 'Traces' },
  { key: '/eval', icon: <BarChartOutlined />, label: 'Evaluation' },
]

const pages = [
  { path: '/', element: <Workbench /> },
  { path: '/tables', element: <Tables /> },
  { path: '/traces', element: <Traces /> },
  { path: '/eval', element: <Evaluation /> },
]

export default function App() {
  const location = useLocation()
  const currentPath = pages.some(page => page.path === location.pathname) ? location.pathname : '/'
  const [mountedPages, setMountedPages] = useState<string[]>(['/'])

  useEffect(() => {
    setMountedPages(prev => prev.includes(currentPath) ? prev : [...prev, currentPath])
  }, [currentPath])

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={200} style={{ background: '#141414', borderRight: '1px solid #303030' }}>
        <div style={{ padding: '16px', color: '#fff', fontWeight: 700, fontSize: 18, textAlign: 'center' }}>
          ConfigForge
        </div>
        <Menu
          mode="inline"
          selectedKeys={[currentPath]}
          style={{ background: 'transparent', borderRight: 0 }}
          items={navItems.map(item => ({
            key: item.key,
            icon: item.icon,
            label: <NavLink to={item.key} style={{ color: 'inherit' }}>{item.label}</NavLink>,
          }))}
        />
      </Sider>
      <Layout>
        <Content style={{ padding: 24, background: '#1a1a1a', minHeight: '100vh' }}>
          {location.pathname !== currentPath && <Navigate to="/" replace />}
          {pages.map(page => mountedPages.includes(page.path) && (
            <div key={page.path} style={{ display: page.path === currentPath ? 'block' : 'none' }}>
              {page.element}
            </div>
          ))}
        </Content>
      </Layout>
    </Layout>
  )
}
