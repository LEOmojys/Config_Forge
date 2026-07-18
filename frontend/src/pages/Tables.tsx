import { useState, useEffect } from 'react'
import { Card, Select, Table, Tag, Typography, Spin, Empty } from 'antd'
import { getTables, getTable } from '../api/client'

export default function Tables() {
  const [tableList, setTableList] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [tableData, setTableData] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getTables().then(setTableList)
  }, [])

  useEffect(() => {
    if (!selected) return
    setLoading(true)
    getTable(selected).then(data => { setTableData(data); setLoading(false) })
  }, [selected])

  const columns = tableData?.headers?.map((h: string) => ({
    title: h,
    dataIndex: h,
    key: h,
    ellipsis: true,
    render: (v: any) => typeof v === 'boolean' ? <Tag color={v ? 'green' : 'red'}>{String(v)}</Tag> : String(v ?? ''),
  })) || []

  const dataSource = tableData?.rows?.map((row: string[], i: number) => {
    const obj: any = { _key: i }
    tableData.headers.forEach((h: string, j: number) => { obj[h] = row[j] })
    return obj
  }) || []

  return (
    <div>
      <Typography.Title level={3} style={{ color: '#fff' }}>Configuration Tables</Typography.Title>
      <Card style={{ background: '#1f1f1f', border: '1px solid #303030', marginBottom: 16 }}>
        <Select
          placeholder="Select a table"
          style={{ width: 300 }}
          options={tableList.map(t => ({ value: t, label: t }))}
          value={selected}
          onChange={setSelected}
          showSearch
        />
        <Tag style={{ marginLeft: 12 }}>{tableList.length} tables loaded</Tag>
      </Card>
      {loading && <Spin style={{ display: 'block', margin: '40px auto' }} />}
      {!loading && !selected && <Empty description="Select a table to view" />}
      {!loading && tableData && (
        <Card style={{ background: '#1f1f1f', border: '1px solid #303030' }}>
          <Typography.Title level={5} style={{ color: '#fff' }}>{tableData.table_name}</Typography.Title>
          <Table
            columns={columns}
            dataSource={dataSource}
            rowKey="_key"
            size="small"
            scroll={{ x: 'max-content' }}
            pagination={{ pageSize: 50 }}
          />
        </Card>
      )}
    </div>
  )
}
