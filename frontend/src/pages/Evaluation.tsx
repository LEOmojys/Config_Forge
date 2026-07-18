import { useState } from 'react'
import { Card, Button, Table, Tag, Typography, Statistic, Row, Col, Spin, Alert } from 'antd'
import { PlayCircleOutlined, TrophyOutlined } from '@ant-design/icons'
import { runEval } from '../api/client'

export default function Evaluation() {
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    setResults(null)
    try {
      const data = await runEval()
      setResults(data)
    } catch (e: any) {
      setError(e.message || 'Eval failed')
    } finally {
      setLoading(false)
    }
  }

  const groupOrder = ['G0_pure_llm', 'G1_pydantic', 'G2_rules', 'G3_full']
  const groupLabels: Record<string, string> = {
    G0_pure_llm: 'G0: Pure LLM',
    G1_pydantic: 'G1: + Pydantic',
    G2_rules: 'G2: + RuleEngine',
    G3_full: 'G3: + Critic (Full)',
  }

  return (
    <div>
      <Typography.Title level={3} style={{ color: '#fff' }}>Evaluation Center</Typography.Title>
      <Card style={{ background: '#1f1f1f', border: '1px solid #303030', marginBottom: 24 }}>
        <Typography.Paragraph style={{ color: '#aaa' }}>
          Runs 20 sample requirements through 4 ablation groups (G0-G3) to measure the effect of each validation layer.
        </Typography.Paragraph>
        <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleRun} loading={loading} size="large">
          Run Ablation Study
        </Button>
      </Card>

      {error && <Alert type="error" message={error} closable style={{ marginBottom: 16 }} />}
      {loading && <Spin size="large" style={{ display: 'block', margin: '40px auto' }} />}

      {results && (
        <div>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            {groupOrder.map(g => results[g] && (
              <Col span={6} key={g}>
                <Card style={{ background: '#1f1f1f', border: '1px solid #303030' }}>
                  <Statistic title={groupLabels[g]} value={`${(results[g].pass_rate * 100).toFixed(0)}%`}
                    suffix="pass" valueStyle={{ color: results[g].pass_rate > 0.8 ? '#52c41a' : '#faad14' }} />
                  <div style={{ color: '#888', fontSize: 12 }}>
                    {results[g].passed}/{results[g].total} samples, avg {results[g].avg_rounds} rounds
                  </div>
                </Card>
              </Col>
            ))}
          </Row>

          {groupOrder.map(g => results[g] && (
            <Card key={g} title={<Typography.Text style={{ color: '#fff' }}>{groupLabels[g]} - Details</Typography.Text>}
              style={{ background: '#1f1f1f', border: '1px solid #303030', marginBottom: 12 }} size="small">
              <Table
                columns={[
                  { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
                  { title: 'Type', dataIndex: 'type', key: 'type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
                  { title: 'Passed', dataIndex: 'passed', key: 'passed', width: 80, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{String(v)}</Tag> },
                  { title: 'Rounds', dataIndex: 'rounds', key: 'rounds', width: 80 },
                  { title: 'Error', dataIndex: 'error', key: 'error', ellipsis: true },
                ]}
                dataSource={results[g].details}
                rowKey="id"
                size="small"
                pagination={false}
              />
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
