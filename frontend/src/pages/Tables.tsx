import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { Card, Select, Table, Tag, Typography, Spin, Empty, Button, Space, Modal, Form, Input, Popconfirm, message } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { addTableRow, deleteTableRow, getTables, getTable, updateTableRow } from '../api/client'

export default function Tables() {
  const [tableList, setTableList] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [tableData, setTableData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const location = useLocation()

  const loadTable = async (name: string) => {
    setLoading(true)
    try {
      const data = await getTable(name)
      setTableData(data)
    } catch (e: any) {
      message.error(e.message || 'Load table failed')
    } finally {
      setLoading(false)
    }
  }

  const refreshTables = async () => {
    setLoading(true)
    try {
      const tables = await getTables()
      setTableList(tables)
      const nextSelected = selected && tables.includes(selected) ? selected : tables[0] || null
      setSelected(nextSelected)
      if (nextSelected) {
        const data = await getTable(nextSelected)
        setTableData(data)
      } else {
        setTableData(null)
      }
    } catch (e: any) {
      message.error(e.message || 'Load tables failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (location.pathname === '/tables') {
      refreshTables()
    }
  }, [location.pathname])

  const showSyncResult = (sync?: any) => {
    const warnings = sync?.warnings || []
    if (warnings.length > 0) {
      message.warning(`CSV saved; JSON sync warnings: ${warnings.join('; ')}`)
    } else {
      message.success(`Saved. JSON files updated: ${sync?.files_updated ?? 0}`)
    }
  }

  const openAdd = () => {
    if (!tableData?.headers?.length) return
    setEditingIndex(null)
    form.setFieldsValue(Object.fromEntries(tableData.headers.map((h: string) => [h, ''])))
    setEditorOpen(true)
  }

  const openEdit = (record: any) => {
    setEditingIndex(record._rowIndex)
    form.setFieldsValue(Object.fromEntries(tableData.headers.map((h: string) => [h, record[h] ?? ''])))
    setEditorOpen(true)
  }

  const saveRow = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const values = form.getFieldsValue()
      const res = editingIndex === null
        ? await addTableRow(selected, values)
        : await updateTableRow(selected, editingIndex, values)
      setTableData(res.table)
      setEditorOpen(false)
      showSyncResult(res.json_sync)
    } catch (e: any) {
      message.error(e.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const removeRow = async (rowIndex: number) => {
    if (!selected) return
    try {
      const res = await deleteTableRow(selected, rowIndex)
      setTableData(res.table)
      showSyncResult(res.json_sync)
    } catch (e: any) {
      message.error(e.message || 'Delete failed')
    }
  }

  const columns = tableData?.headers?.map((h: string) => ({
    title: h,
    dataIndex: h,
    key: h,
    ellipsis: true,
    render: (v: any) => typeof v === 'boolean' ? <Tag color={v ? 'green' : 'red'}>{String(v)}</Tag> : String(v ?? ''),
  })) || []

  if (columns.length > 0) {
    columns.push({
      title: 'Actions',
      dataIndex: '_actions',
      key: '_actions',
      width: 120,
      fixed: 'right',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Popconfirm title="Delete this row?" okText="Delete" okButtonProps={{ danger: true }} onConfirm={() => removeRow(record._rowIndex)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    } as any)
  }

  const dataSource = tableData?.rows?.map((row: string[], i: number) => {
    const obj: any = { _key: i, _rowIndex: i }
    tableData.headers.forEach((h: string, j: number) => { obj[h] = row[j] })
    return obj
  }) || []

  return (
    <div>
      <Typography.Title level={3} style={{ color: '#fff' }}>Configuration Tables</Typography.Title>
      <Card style={{ background: '#1f1f1f', border: '1px solid #303030', marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="Select a table"
            style={{ width: 300 }}
            options={tableList.map(t => ({ value: t, label: t }))}
            value={selected}
            onChange={(value) => { setSelected(value); loadTable(value) }}
            showSearch
          />
          <Tag>{tableList.length} tables loaded</Tag>
          <Button icon={<ReloadOutlined />} onClick={refreshTables}>Refresh</Button>
          <Button type="primary" icon={<PlusOutlined />} disabled={!selected || !tableData?.headers?.length} onClick={openAdd}>Add Row</Button>
        </Space>
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
      <Modal
        title={editingIndex === null ? 'Add Row' : `Edit Row #${editingIndex + 1}`}
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        onOk={saveRow}
        confirmLoading={saving}
        width={720}
        destroyOnClose={false}
      >
        <Form form={form} layout="vertical">
          {tableData?.headers?.map((header: string) => (
            <Form.Item key={header} label={header} name={header}>
              <Input />
            </Form.Item>
          ))}
        </Form>
      </Modal>
    </div>
  )
}
