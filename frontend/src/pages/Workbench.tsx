import { useState, useRef } from 'react'
import { Card, Form, Select, Input, InputNumber, Button, Switch, Space, Tag, Typography, Divider, Alert, Collapse, Timeline, Table, Progress } from 'antd'
import { SendOutlined, ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'

const { TextArea } = Input

const TYPE_OPTIONS = [
  { value: 'skill', label: 'Skill' },
  { value: 'monster', label: 'Monster' },
  { value: 'quest', label: 'Quest' },
]

interface SSEEvent {
  type: string
  timestamp: number
  data: Record<string, any>
}

export default function Workbench() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [events, setEvents] = useState<SSEEvent[]>([])
  const abortRef = useRef<AbortController | null>(null)

  const handleGenerate = async (values: any) => {
    setLoading(true)
    setError(null)
    setResult(null)
    setEvents([])

    try {
      // Step 1: POST /api/generate → get job_id immediately
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      })
      if (!res.ok) throw new Error(await res.text())
      const { job_id, trace_id } = await res.json()

      // Step 2: Connect SSE stream
      const controller = new AbortController()
      abortRef.current = controller

      const sseRes = await fetch(`/api/jobs/${job_id}/events`, {
        signal: controller.signal,
      })
      if (!sseRes.body) throw new Error('SSE not supported')

      const reader = sseRes.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let finalResult: any = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const evt: SSEEvent = JSON.parse(line.slice(6))
              setEvents(prev => [...prev, evt])

              if (evt.type === 'done') {
                finalResult = evt.data
                reader.cancel()
              } else if (evt.type === 'error') {
                setError(evt.data?.message || 'Unknown error')
                reader.cancel()
              }
            } catch {}
          }
        }
      }

      if (finalResult) {
        setResult(finalResult)
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        setError(e.message || 'Generation failed')
      }
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }

  // Build visual timeline from events
  const timelineItems = events
    .filter(e => !['start', 'close'].includes(e.type))
    .map((e, i) => {
      const d = e.data
      let color = '#1677ff'
      let icon: React.ReactNode = <LoadingOutlined />
      let children: React.ReactNode = null

      switch (e.type) {
        case 'batch_start':
          return {
            color: 'blue',
            dot: <Tag color="blue">BATCH</Tag>,
            children: <span style={{ color: '#ccc' }}>Batch started: {d.total} {d.job_type} items</span>,
          }
        case 'batch_item_start':
          return {
            color,
            dot: icon,
            children: <span style={{ color: '#ccc' }}>Generating item {d.index}/{d.total}...</span>,
          }
        case 'batch_item_done':
          return {
            color: d.status === 'passed' ? 'green' : 'orange',
            dot: <CheckCircleOutlined />,
            children: <span style={{ color: d.status === 'passed' ? '#52c41a' : '#faad14' }}>
              Item {d.index}/{d.total}: {d.name || d.id || d.trace_id} ({d.status})
            </span>,
          }
        case 'batch_item_error':
          return {
            color: 'red',
            dot: <CloseCircleOutlined />,
            children: <span style={{ color: '#ff4d4f' }}>
              Item {d.index}/{d.total} failed: {d.error}
            </span>,
          }
        case 'round_start':
          return { color: 'gray', dot: <Tag>R{d.round}</Tag>, children: <span style={{ color: '#888' }}>Round {d.round} start</span> }
        case 'generating':
          return { color, dot: icon, children: <span style={{ color: '#ccc' }}>LLM generating...</span> }
        case 'generated':
          return { color: 'green', dot: <CheckCircleOutlined />, children: <span style={{ color: '#52c41a' }}>Generated {d.bundle_summary}</span> }
        case 'validating':
          return { color, dot: icon, children: <span style={{ color: '#ccc' }}>Running RuleEngine...</span> }
        case 'violation':
          return {
            color: d.severity === 'error' ? 'red' : 'orange',
            dot: d.severity === 'error' ? <CloseCircleOutlined /> : <Tag color="orange">WARN</Tag>,
            children: <span style={{ color: d.severity === 'error' ? '#ff4d4f' : '#faad14', fontSize: 12 }}>
              [{d.rule_id}] {d.table}.{d.field}: {d.message}
            </span>,
          }
        case 'reviewing':
          return { color, dot: icon, children: <span style={{ color: '#ccc' }}>Critic reviewing...</span> }
        case 'reviewed':
          return {
            color: d.approved ? 'green' : 'red',
            dot: d.approved ? <CheckCircleOutlined /> : <CloseCircleOutlined />,
            children: <span style={{ color: d.approved ? '#52c41a' : '#ff4d4f' }}>
              Critic {d.approved ? 'Approved' : 'Rejected'}
              {d.issues?.length > 0 && <span style={{ fontSize: 11 }}> ({d.issues.length} issues)</span>}
            </span>,
          }
        case 'round_end':
          return {
            color: d.passed ? 'green' : 'red',
            dot: d.passed ? <CheckCircleOutlined /> : <CloseCircleOutlined />,
            children: <span style={{ color: d.passed ? '#52c41a' : '#ff4d4f' }}>
              Round complete: {d.passed ? 'PASSED' : `FAILED (${d.errors_count} errors)`}
            </span>,
          }
        case 'done':
          if (d.is_batch) {
            return {
              color: d.status === 'passed' ? 'green' : 'orange',
              dot: d.status === 'passed' ? <CheckCircleOutlined /> : <CloseCircleOutlined />,
              children: <Tag color={d.status === 'passed' ? 'green' : 'orange'}>
                Batch {d.status}: {d.succeeded}/{d.batch_count} completed
              </Tag>,
            }
          }
          return {
            color: d.status === 'passed' ? 'green' : 'orange',
            dot: d.status === 'passed' ? <CheckCircleOutlined /> : <CloseCircleOutlined />,
            children: <Tag color={d.status === 'passed' ? 'green' : 'orange'}>
              {d.status === 'passed' ? 'PASSED' : 'NEED HUMAN'} in {d.rounds} rounds
            </Tag>,
          }
        case 'error':
          return { color: 'red', dot: <CloseCircleOutlined />, children: <span style={{ color: '#ff4d4f' }}>{d.message}</span> }
        default:
          return null
      }
    })
    .filter(Boolean)

  return (
    <div>
      <Typography.Title level={3} style={{ color: '#fff' }}>Generation Workbench</Typography.Title>
      <div style={{ display: 'grid', gridTemplateColumns: '420px 1fr', gap: 24 }}>
        <Card title="Requirement" style={{ background: '#1f1f1f', border: '1px solid #303030' }}>
          <Form form={form} layout="vertical" onFinish={handleGenerate} initialValues={{ job_type: 'monster', enable_critic: true }}>
            <Form.Item label="Type" name="job_type" rules={[{ required: true }]}>
              <Select options={TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item label="Requirement" name="requirement" rules={[{ required: true, min: 3 }]}>
              <TextArea rows={4} placeholder="e.g. Generate a level 30 fire-element elite monster with high HP and summoner AI" />
            </Form.Item>
            <Form.Item label="Batch Count" name="batch_count">
              <InputNumber min={1} max={20} precision={0} placeholder="Fallback when requirement has no count" style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="Enable Critic" name="enable_critic" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} icon={<SendOutlined />} block>
              Generate
            </Button>
          </Form>
        </Card>

        <div>
          {error && <Alert type="error" message={error} closable style={{ marginBottom: 16 }} />}

          {events.length > 0 && (
            <Card title="Generation Progress" size="small" style={{ background: '#1f1f1f', border: '1px solid #303030', marginBottom: 16 }}>
              <Timeline items={timelineItems as any} style={{ marginTop: 8 }} />
            </Card>
          )}

          {result && (
            <Card title={`Result: ${result.status === 'passed' ? 'Passed' : result.status === 'partial' ? 'Partial' : 'Needs Review'}`} style={{ background: '#1f1f1f', border: '1px solid #303030' }}>
              <Space style={{ marginBottom: 12 }} wrap>
                <Tag color={result.status === 'passed' ? 'green' : 'orange'}>{result.status}</Tag>
                {result.is_batch
                  ? <Tag>Items: {result.succeeded}/{result.batch_count}</Tag>
                  : <Tag>Rounds: {result.rounds}</Tag>}
                <Tag color="blue">{result.type}</Tag>
              </Space>
              {result.is_batch && (
                <Progress
                  percent={Math.round((result.succeeded / result.batch_count) * 100)}
                  status={result.failed > 0 ? 'exception' : 'success'}
                  style={{ marginBottom: 12 }}
                />
              )}
              <Collapse
                items={[
                  ...(result.is_batch ? [{
                    key: 'items',
                    label: `Batch Items (${result.items?.length || 0})`,
                    children: <Table
                      dataSource={result.items || []}
                      rowKey={(row: any) => row.trace_id || String(row.index)}
                      size="small"
                      pagination={false}
                      scroll={{ x: 'max-content' }}
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
                    />,
                  }] : []),
                  {
                    key: 'json',
                    label: result.is_batch ? `Generated JSON (${result.succeeded} bundles)` : 'Generated JSON',
                    children: <pre style={{ color: '#ccc', fontSize: 12, maxHeight: 500, overflow: 'auto' }}>{JSON.stringify(result.bundle, null, 2)}</pre>,
                  },
                  {
                    key: 'csv',
                    label: `CSV Output (${result.csv_files?.length || 0} files)`,
                    children: <pre style={{ color: '#ccc', fontSize: 12 }}>{(result.csv_files || []).join('\n') || 'No CSV files'}</pre>,
                  },
                ]}
                style={{ background: '#1a1a1a' }}
              />
              <Divider />
              <Space>
                <Button icon={<ReloadOutlined />} onClick={() => handleGenerate(form.getFieldsValue())}>Regenerate</Button>
              </Space>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
