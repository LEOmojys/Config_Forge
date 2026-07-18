import { useState, useEffect } from 'react'
import { Card, Table, Tag, Typography, Button, Drawer, Collapse, Timeline, Space, Spin } from 'antd'
import { EyeOutlined, ReloadOutlined } from '@ant-design/icons'
import { getTraces, getTrace } from '../api/client'

export default function Traces() {
  const [traces, setTraces] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const loadTraces = async () => {
    setLoading(true)
    const data = await getTraces()
    setTraces(data)
    setLoading(false)
  }

  useEffect(() => { loadTraces() }, [])

  const viewDetail = async (traceId: string) => {
    const data = await getTrace(traceId)
    setDetail(data)
    setDrawerOpen(true)
  }

  const columns = [
    { title: 'ID', dataIndex: 'trace_id', key: 'id', ellipsis: true, width: 200 },
    { title: 'Type', dataIndex: 'job_type', key: 'type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
    { title: 'Requirement', dataIndex: 'requirement', key: 'req', ellipsis: true },
    {
      title: 'Status', dataIndex: 'status', key: 'status', width: 120,
      render: (v: string) => <Tag color={v === 'passed' ? 'green' : v === 'need_human' ? 'orange' : 'blue'}>{v}</Tag>,
    },
    { title: 'Rounds', dataIndex: 'rounds', key: 'rounds', width: 60, render: (_: any, r: any) => r.rounds?.length || '-' },
    { title: 'Created', dataIndex: 'created_at', key: 'ts', width: 180, render: (v: string) => v?.slice(0, 19).replace('T', ' ') },
    {
      title: '', key: 'action', width: 60,
      render: (_: any, r: any) => <Button size="small" icon={<EyeOutlined />} onClick={() => viewDetail(r.trace_id)} />,
    },
  ]

  return (
    <div>
      <Typography.Title level={3} style={{ color: '#fff' }}>
        Trace Replay
        <Button icon={<ReloadOutlined />} onClick={loadTraces} style={{ marginLeft: 12 }} size="small">Refresh</Button>
      </Typography.Title>
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
            </Space>
            <Typography.Paragraph style={{ color: '#aaa' }}>{detail.requirement}</Typography.Paragraph>
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
