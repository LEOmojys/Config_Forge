import { useState } from 'react'
import { Card, Button, Table, Tag, Typography, Statistic, Row, Col, Spin, Alert, Progress } from 'antd'
import { PlayCircleOutlined, TrophyOutlined } from '@ant-design/icons'
import { runEval } from '../api/client'

interface GroupProgress {
  group: string
  groupIndex: number
  label: string
  done: number
  total: number
}

export default function Evaluation() {
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<GroupProgress | null>(null)
  const [log, setLog] = useState<string[]>([])

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    setResults(null)
    setProgress(null)
    setLog([])
    try {
      // Step 1: POST /api/eval/run → get job_id immediately
      const { job_id } = await runEval()

      // Step 2: Connect SSE stream for live progress
      const sseRes = await fetch(`/api/jobs/${job_id}/events`)
      if (!sseRes.body) throw new Error('SSE not supported')

      const reader = sseRes.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let finalResults: any = null
      let runError: string | null = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() || ''

        for (const chunk of chunks) {
          if (!chunk.startsWith('data: ')) continue
          try {
            const evt = JSON.parse(chunk.slice(6))
            const d = evt.data
            if (evt.type === 'group_start') {
              setProgress({ group: d.group, groupIndex: d.group_index || 0, label: d.label, done: 0, total: d.total })
              setLog(prev => [...prev, `▶ Group ${d.group_index || '?'}/4 ${d.label} — ${d.total} samples`])
            } else if (evt.type === 'sample_done') {
              setProgress(p => (p ? { ...p, done: d.index } : p))
              setLog(prev => [...prev.slice(-60),
                `  sample ${d.index}/${d.total}: ${d.passed ? 'pass' : 'FAIL'} (${d.rounds} rounds)${d.error ? ' — ' + d.error : ''}`])
            } else if (evt.type === 'group_done') {
              const g = d.result
              setLog(prev => [...prev.slice(-60),
                g.disabled
                  ? `⏸ ${d.group}: not measured — ${g.note}`
                  : `✔ ${d.group}: ${g.passed}/${g.total} passed, ${(g.pass_rate * 100).toFixed(0)}%, avg ${g.avg_rounds} rounds`])
            } else if (evt.type === 'done') {
              finalResults = d
              reader.cancel()
            } else if (evt.type === 'error') {
              runError = d?.message || 'Eval failed'
              reader.cancel()
            }
          } catch { /* ignore malformed chunks */ }
        }
      }

      if (finalResults) {
        setResults(finalResults)
      } else if (runError) {
        setError(runError)
      } else {
        setError('实验流中断：后端可能已重启（如 --reload 触发）或实验被中止。已完成的进度保存在 output/eval/eval_running_*.json，可检查后重新运行。')
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        setError(e.message || 'Eval failed')
      }
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
        {loading && progress && (
          <Card size="small" title={<Typography.Text style={{ color: '#fff' }}>Running: Group {progress.groupIndex}/4 — {progress.label}</Typography.Text>}
            style={{ background: '#141414', border: '1px solid #303030', marginTop: 16 }}>
            <Progress
              percent={progress.total ? Math.round((progress.done / progress.total) * 100) : 0}
              status="active"
              format={() => `${progress.done}/${progress.total} samples`}
            />
            <div style={{ color: '#888', fontSize: 12, maxHeight: 240, overflowY: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace', marginTop: 8 }}>
              {log.slice(-30).join('\n')}
            </div>
          </Card>
        )}
      </Card>

      {error && <Alert type="error" message={error} closable style={{ marginBottom: 16 }} />}

      {results && (
        <div>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            {groupOrder.map(g => results[g] && (
              <Col span={6} key={g}>
                <Card style={{ background: '#1f1f1f', border: '1px solid #303030' }}>
                  <Statistic title={groupLabels[g]} value={results[g].disabled ? 'N/A' : `${(results[g].pass_rate * 100).toFixed(0)}%`}
                    suffix={results[g].disabled ? '' : 'pass'} valueStyle={{ color: results[g].disabled ? '#8c8c8c' : results[g].pass_rate > 0.8 ? '#52c41a' : '#faad14' }} />
                  <div style={{ color: '#888', fontSize: 12 }}>
                    {results[g].disabled ? results[g].note : `${results[g].passed}/${results[g].total} samples, avg ${results[g].avg_rounds} rounds`}
                  </div>
                  {!results[g].disabled && typeof results[g].contract_pass_rate === 'number' && (
                    <div style={{ color: '#bae0ff', fontSize: 12, marginTop: 4 }}>
                      contract {(results[g].contract_pass_rate * 100).toFixed(0)}% ({results[g].contract_passed}/{results[g].total})
                    </div>
                  )}
                </Card>
              </Col>
            ))}
          </Row>

          <Typography.Paragraph style={{ color: '#777', fontSize: 12 }}>
            pass = 该组门禁下的管线状态通过率（及格线随组变化）；contract = 统一裁判——最终产物经完整规则引擎离线审计的通过率（跨组可比的消融金标准）。
          </Typography.Paragraph>

          {results._report && (
            <Card size="small" title={<Typography.Text style={{ color: '#fff' }}><TrophyOutlined /> Report Saved</Typography.Text>}
              style={{ background: '#1f1f1f', border: '1px solid #303030', marginBottom: 12 }}>
              <Typography.Paragraph style={{ color: '#888', fontSize: 12, marginBottom: 0 }}>
                {results._report.json}<br />{results._report.markdown}
              </Typography.Paragraph>
            </Card>
          )}

          {groupOrder.map(g => results[g] && (
            <Card key={g} title={<Typography.Text style={{ color: '#fff' }}>{groupLabels[g]} - Details</Typography.Text>}
              style={{ background: '#1f1f1f', border: '1px solid #303030', marginBottom: 12 }} size="small">
              {results[g].disabled ? (
                <Alert type="info" message={results[g].note} showIcon />
              ) : <Table
                columns={[
                  { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
                  { title: 'Type', dataIndex: 'type', key: 'type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
                  { title: 'Passed', dataIndex: 'passed', key: 'passed', width: 80, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{String(v)}</Tag> },
                  { title: 'Contract', dataIndex: 'audit_passed', key: 'audit_passed', width: 110,
                    render: (v: boolean | null, row: any) =>
                      v === true ? <Tag color="blue">✓</Tag>
                        : v === false ? <Tag color="orange">{row.audit_errors ?? 'no output'}</Tag>
                          : <Tag>-</Tag> },
                  { title: 'Rounds', dataIndex: 'rounds', key: 'rounds', width: 80 },
                  { title: 'Error', dataIndex: 'error', key: 'error', ellipsis: true },
                ]}
                dataSource={results[g].details}
                rowKey="id"
                size="small"
                pagination={false}
              />}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
