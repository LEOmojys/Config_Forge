import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { Card, Table, Tag, Typography, Button, Drawer, Collapse, Space, Popconfirm, message } from 'antd'
import { DeleteOutlined, EyeOutlined, ReloadOutlined } from '@ant-design/icons'
import { clearTraces, deleteTrace, getTraces, getTrace } from '../api/client'

export default function Traces() {
  const [traces, setTraces] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const location = useLocation()

  const loadTraces = async () => {
    setLoading(true)
    try {
      const data = await getTraces()
      setTraces([...data].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))))
    } catch (e: any) {
      message.error(e.message || 'Load traces failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (location.pathname === '/traces') {
      loadTraces()
    }
  }, [location.pathname])

  const viewDetail = async (traceId: string) => {
    const data = await getTrace(traceId)
    setDetail(data)
    setDrawerOpen(true)
  }

  const removeTrace = async (traceId: string) => {
    try {
      await deleteTrace(traceId)
      if (detail?.trace_id === traceId) {
        setDrawerOpen(false)
        setDetail(null)
      }
      await loadTraces()
      message.success('Trace deleted')
    } catch (e: any) {
      message.error(e.message || 'Delete failed')
    }
  }

  const cleanTraces = async (status?: string) => {
    try {
      const res = await clearTraces(status)
      if (!status || detail?.status === status) {
        setDrawerOpen(false)
        setDetail(null)
      }
      await loadTraces()
      message.success(`Deleted ${res.deleted} trace records`)
    } catch (e: any) {
      message.error(e.message || 'Clean failed')
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'trace_id', key: 'id', ellipsis: true, width: 200 },
    { title: 'Type', dataIndex: 'job_type', key: 'type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
    { title: 'Requirement', dataIndex: 'requirement', key: 'req', ellipsis: true },
    {
      title: 'Status', dataIndex: 'status', key: 'status', width: 120,
      render: (v: string) => <Tag color={v === 'passed' ? 'green' : ['partial', 'need_human'].includes(v) ? 'orange' : v === 'failed' ? 'red' : 'blue'}>{v}</Tag>,
    },
    {
      title: 'Progress', dataIndex: 'rounds', key: 'rounds', width: 90,
      render: (_: any, r: any) => r.is_batch
        ? `${r.batch_items?.length || 0}/${r.batch_count}`
        : r.rounds?.length || '-',
    },
    { title: 'Created', dataIndex: 'created_at', key: 'ts', width: 180, render: (v: string) => v?.slice(0, 19).replace('T', ' ') },
    {
      title: '', key: 'action', width: 100,
      render: (_: any, r: any) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => viewDetail(r.trace_id)} />
          <Popconfirm title="Delete this trace?" okText="Delete" okButtonProps={{ danger: true }} onConfirm={() => removeTrace(r.trace_id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]
  const finalBundle = detail?.rounds?.length ? detail.rounds[detail.rounds.length - 1]?.bundle : null

  return (
    <div>
      <Typography.Title level={3} style={{ color: '#fff' }}>
        Trace Replay
      </Typography.Title>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={loadTraces}>Refresh</Button>
        <Popconfirm title="Delete all running traces?" okText="Clean" okButtonProps={{ danger: true }} onConfirm={() => cleanTraces('running')}>
          <Button danger>Clean Running</Button>
        </Popconfirm>
        <Popconfirm title="Delete all need_human traces?" okText="Clean" okButtonProps={{ danger: true }} onConfirm={() => cleanTraces('need_human')}>
          <Button danger>Clean Need Human</Button>
        </Popconfirm>
        <Popconfirm title="Delete all trace records?" okText="Delete All" okButtonProps={{ danger: true }} onConfirm={() => cleanTraces()}>
          <Button danger icon={<DeleteOutlined />}>Clear All</Button>
        </Popconfirm>
      </Space>
      <Card style={{ background: '#1f1f1f', border: '1px solid #303030' }}>
        <Table columns={columns} dataSource={traces} rowKey="trace_id" size="small" loading={loading}
          pagination={{ pageSize: 20 }} scroll={{ x: 'max-content' }} />
      </Card>
      <Drawer title="Trace Detail" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={700}
        styles={{ body: { background: '#1a1a1a' } }}>
        {detail && (
          <div>
            <Space style={{ marginBottom: 16 }}>
              <Tag color={detail.status === 'passed' ? 'green' : 'orange'}>{detail.status}</Tag>
              <Tag>{detail.job_type}</Tag>
              {detail.is_batch && <Tag color="blue">Batch {detail.batch_items?.length || 0}/{detail.batch_count}</Tag>}
            </Space>
            <Typography.Paragraph style={{ color: '#aaa' }}>{detail.requirement}</Typography.Paragraph>
            {detail.is_batch && (
              <Table
                dataSource={detail.batch_items || []}
                rowKey={(row: any) => row.trace_id || String(row.index)}
                size="small"
                pagination={false}
                scroll={{ x: 'max-content' }}
                style={{ marginBottom: 16 }}
                columns={[
                  { title: '#', dataIndex: 'index', key: 'index', width: 50 },
                  { title: 'Name', dataIndex: 'name', key: 'name', ellipsis: true },
                  { title: 'ID', dataIndex: 'id', key: 'id', ellipsis: true },
                  {
                    title: 'Status', dataIndex: 'status', key: 'status', width: 100,
                    render: (value: string) => <Tag color={value === 'passed' ? 'green' : 'red'}>{value}</Tag>,
                  },
                  { title: 'Trace', dataIndex: 'trace_id', key: 'trace_id', ellipsis: true },
                ]}
              />
            )}
            {finalBundle && (
              <Collapse style={{ background: '#1a1a1a', marginBottom: 16 }} defaultActiveKey={['bundle']} items={[{
                key: 'bundle',
                label: 'Generated Bundle',
                children: <pre style={{ color: '#ccc', fontSize: 11, maxHeight: 420, overflow: 'auto' }}>
                  {JSON.stringify(finalBundle, null, 2)}
                </pre>,
              }]} />
            )}
            <Typography.Title level={5} style={{ color: '#fff', marginTop: 24 }}>Rounds</Typography.Title>
            {detail.rounds?.map((r: any, i: number) => (
              <Card key={i} size="small" style={{ background: '#222', marginBottom: 8, border: '1px solid #333' }}
                title={<Typography.Text style={{ color: '#fff' }}>Round {r.round} {r.passed ? <Tag color="green">Passed</Tag> : <Tag color="red">Failed</Tag>}</Typography.Text>}>
                {r.violations?.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <Typography.Text type="warning">Violations:</Typography.Text>
                    {r.violations.map((v: any, j: number) => (
                      <div key={j} style={{ color: '#f5a623', fontSize: 12, paddingLeft: 12 }}>
                        [{v.rule_id}] {v.table}.{v.field}: {v.message}
                      </div>
                    ))}
                  </div>
                )}
                {r.critic && (
                  <div>
                    <Typography.Text type="secondary">Critic: </Typography.Text>
                    <Tag color={r.critic.approved ? 'green' : 'red'}>{r.critic.approved ? 'Approved' : 'Rejected'}</Tag>
                    {r.critic.issues?.map((issue: string, j: number) => (
                      <div key={j} style={{ color: '#ff7875', fontSize: 12, paddingLeft: 12 }}>- {issue}</div>
                    ))}
                  </div>
                )}
              </Card>
            ))}
            <Collapse style={{ background: '#1a1a1a' }} items={[{
              key: 'raw',
              label: 'Raw JSON',
              children: <pre style={{ color: '#ccc', fontSize: 11, maxHeight: 400, overflow: 'auto' }}>
                {JSON.stringify(detail, null, 2)}
              </pre>,
            }]} />
          </div>
        )}
      </Drawer>
    </div>
  )
}
