import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useStore } from './store'

const s = () => useStore.getState()

describe('undo and redo', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]'))
    s().reset()
  })

  it('undoes and redoes adding a node', () => {
    s().addNode()
    s().addNode()
    expect(s().nodes).toHaveLength(2)
    s().undo()
    expect(s().nodes).toHaveLength(1)
    s().undo()
    expect(s().nodes).toHaveLength(0)
    expect(s().canUndo).toBe(false)
    expect(s().canRedo).toBe(true)
    s().redo()
    s().redo()
    expect(s().nodes).toHaveLength(2)
    expect(s().canRedo).toBe(false)
  })

  it('does nothing when there is nothing to undo or redo', () => {
    s().undo()
    s().redo()
    expect(s().nodes).toHaveLength(0)
    expect(s().dirty).toBe(false) // no phantom edit
  })

  it('a new edit after undo discards the redo branch', () => {
    s().addNode()
    s().undo()
    expect(s().canRedo).toBe(true)
    s().addNode()
    expect(s().canRedo).toBe(false)
    s().redo()
    expect(s().nodes).toHaveLength(1)
  })

  it('treats a burst of typing as one undo step', () => {
    s().addNode()
    const id = s().nodes[0].id
    for (const t of ['a', 'ab', 'abc', 'abcd']) s().updateConfig(id, { source: t })
    expect(s().nodes[0].data.config.source).toBe('abcd')
    s().undo() // one step reverts the whole burst
    expect(s().nodes[0].data.config.source).toContain('def main') // back to the template code
    expect(s().nodes).toHaveLength(1)
  })

  it('keeps separate steps for edits to different fields', () => {
    s().addNode()
    const id = s().nodes[0].id
    s().setName('first')
    s().updateData(id, { name: 'renamed' })
    s().undo()
    expect(s().nodes[0].data.name).not.toBe('renamed')
    expect(s().workflowName).toBe('first')
    s().undo()
    expect(s().workflowName).toBe('Untitled')
  })

  it('undoing a deletion brings the node and its edges back', () => {
    s().addNode()
    s().addNode()
    const [a, b] = s().nodes.map((n) => n.id)
    s().onConnect({ source: a, target: b, sourceHandle: null, targetHandle: null })
    expect(s().edges).toHaveLength(1)
    s().onNodesChange([{ type: 'remove', id: a }])
    s().onEdgesChange([{ type: 'remove', id: s().edges[0].id }])
    expect(s().nodes).toHaveLength(1)
    expect(s().edges).toHaveLength(0)
    s().undo()
    s().undo()
    expect(s().nodes).toHaveLength(2)
    expect(s().edges).toHaveLength(1)
  })

  it('moving a node is one step however many mouse moves it takes', () => {
    s().addNode()
    const id = s().nodes[0].id
    const start = s().nodes[0].position
    s().beginDrag()
    for (let i = 1; i <= 20; i++) s().onNodesChange([{ type: 'position', id, position: { x: i * 5, y: 0 }, dragging: true }])
    expect(s().nodes[0].position.x).toBe(100)
    s().undo()
    expect(s().nodes[0].position).toEqual(start)
  })

  it('marks the workflow dirty so autosave persists an undo', () => {
    s().addNode()
    useStore.setState({ dirty: false, saveState: 'saved' })
    s().undo()
    expect(s().dirty).toBe(true)
  })

  it('clears the selection when the selected node disappears, and resets with the workflow', () => {
    s().addNode()
    expect(s().selectedId).not.toBeNull()
    s().undo()
    expect(s().selectedId).toBeNull()
    s().redo()
    s().reset()
    expect(s().canUndo).toBe(false)
    expect(s().canRedo).toBe(false)
  })

  it('refuses self-loops, duplicates and cycles even if the canvas lets one through', () => {
    s().addNode()
    s().addNode()
    s().addNode()
    const [a, b, c] = s().nodes.map((n) => n.id)
    const link = (x: string, y: string) => s().onConnect({ source: x, target: y, sourceHandle: null, targetHandle: null })
    link(a, b)
    link(b, c)
    link(a, a)
    link(a, b)
    link(c, a)
    expect(s().edges.map((e) => `${e.source}>${e.target}`)).toEqual([`${a}>${b}`, `${b}>${c}`])
  })
})
