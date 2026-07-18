import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
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

export default function App() {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={200} style={{ background: '#141414', borderRight: '1px solid #303030' }}>
        <div style={{ padding: '16px', color: '#fff', fontWeight: 700, fontSize: 18, textAlign: 'center' }}>
          ConfigForge
        </div>
        <Menu
          mode="inline"
          defaultSelectedKeys={['/']}
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
          <Routes>
            <Route path="/" element={<Workbench />} />
            <Route path="/tables" element={<Tables />} />
            <Route path="/traces" element={<Traces />} />
            <Route path="/eval" element={<Evaluation />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
