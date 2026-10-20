import {
  applyNodeChanges,
  Background,
  BaseEdge,
  Controls,
  getBezierPath,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type EdgeProps,
  type NodeChange,
} from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'
import { useExplorer } from '../state/explorer'
import { DirNode, FileNode } from './ExplorerNodes'
import {
  buildGraph,
  fileId,
  languageCounts,
  layoutGraph,
  type ExplorerEdge,
  type ExplorerNode,
} from './graph'
import { searchFiles } from './tree'

function ContainsEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
}: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  return (
    <BaseEdge
      id={id}
      path={path}
      className={`xe xe-contains${selected ? ' selected' : ''}`}
      interactionWidth={16}
    />
  )
}

const nodeTypes = { file: FileNode, dir: DirNode }
const edgeTypes = { contains: ContainsEdge }

function Canvas({ repoName, theme }: { repoName: string; theme: 'dark' | 'light' }) {
  const files = useExplorer((s) => s.files)
  const expanded = useExplorer((s) => s.expanded)
  const languages = useExplorer((s) => s.languages)
  const selectedPath = useExplorer((s) => s.selectedPath)
  const focus = useExplorer((s) => s.focus)
  const selectedEdge = useExplorer((s) => s.selectedEdge)
  const { selectFile, setSelectedEdge, reveal, toggleLanguage, clearLanguages, collapseAll } =
    useExplorer.getState()
  const rf = useReactFlow()
  const [query, setQuery] = useState('')

  const built = useMemo(() => {
    const g = buildGraph(files, repoName, { expanded, languages })
    return { ...g, nodes: layoutGraph(g.nodes, g.edges) }
  }, [files, repoName, expanded, languages])

  // Positions are local so nodes can be dragged; a new layout (expand/filter) replaces them.
  const [nodes, setNodes] = useState<ExplorerNode[]>(built.nodes)
  const [layoutSeen, setLayoutSeen] = useState(built.nodes)
  if (layoutSeen !== built.nodes) {
    setLayoutSeen(built.nodes) // adopt the new layout during render, not in an effect
    setNodes(built.nodes)
  }
  const onNodesChange = (changes: NodeChange<ExplorerNode>[]) =>
    setNodes((ns) =>
      applyNodeChanges(
        changes.filter((c) => c.type !== 'select'),
        ns,
      ),
    )

  const shownNodes = useMemo(
    () => nodes.map((n) => (n.id === fileId(selectedPath ?? '\0') ? { ...n, selected: true } : n)),
    [nodes, selectedPath],
  )
  const edges: ExplorerEdge[] = useMemo(
    () => built.edges.map((e) => (e.id === selectedEdge ? { ...e, selected: true } : e)),
    [built.edges, selectedEdge],
  )

  // fit the view whenever the set of visible nodes changes shape
  const shapeKey = built.nodes.map((n) => n.id).join('|')
  useEffect(() => {
    const t = setTimeout(
      () => void rf.fitView({ padding: 0.15, duration: 200, minZoom: 0.6, maxZoom: 1 }),
      30,
    )
    return () => clearTimeout(t)
  }, [shapeKey, rf])

  // centre on a revealed file once its node exists
  useEffect(() => {
    if (!focus) return
    const n = built.nodes.find((x) => x.id === fileId(focus.path))
    if (n) void rf.setCenter(n.position.x + 105, n.position.y + 29, { zoom: 1, duration: 300 })
  }, [focus, built.nodes, rf])

  const hits = useMemo(() => searchFiles(files, query, 50), [files, query])
  const langs = useMemo(() => languageCounts(files).slice(0, 8), [files])
  const selectedEdgeData = built.edges.find((e) => e.id === selectedEdge)?.data

  return (
    <ReactFlow
      nodes={shownNodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={(_, n) => {
        if (n.type === 'file') void selectFile(n.data.path)
      }}
      onEdgeClick={(_, e) => setSelectedEdge(e.id)}
      onPaneClick={() => setSelectedEdge(null)}
      nodesConnectable={false}
      deleteKeyCode={null}
      colorMode={theme}
      minZoom={0.05}
      fitView
    >
      <Background />
      <Controls showInteractive={false} />
      {built.nodes.length > 12 && <MiniMap pannable zoomable />}
      <Panel position="top-left" className="graph-tools">
        <input
          type="search"
          aria-label="Find a file in the graph"
          placeholder="Find file…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && hits[0]) {
              void reveal(hits[0].path)
              setQuery('')
            }
          }}
        />
        {query.trim() && (
          <ul className="graph-hits" aria-label="Matching files">
            {hits.length === 0 && <li className="muted">No match</li>}
            {hits.slice(0, 8).map((h) => (
              <li key={h.path}>
                <button
                  onClick={() => {
                    void reveal(h.path)
                    setQuery('')
                  }}
                >
                  {h.path}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="chips" role="group" aria-label="Filter by language">
          {langs.map(([l, n]) => (
            <button
              key={l}
              className={`chip${languages.has(l) ? ' on' : ''}`}
              aria-pressed={languages.has(l)}
              onClick={() => toggleLanguage(l)}
            >
              {l} <span className="muted">{n}</span>
            </button>
          ))}
          {languages.size > 0 && (
            <button className="link-button" onClick={clearLanguages}>
              Clear
            </button>
          )}
          <button className="link-button" onClick={collapseAll}>
            Collapse all
          </button>
        </div>
      </Panel>
      <Panel position="bottom-left" className="graph-legend" aria-label="Legend">
        <div>
          <svg width="28" height="8" aria-hidden="true">
            <path d="M0 4 H28" className="xe-contains" />
          </svg>{' '}
          Folder contains item (structure)
        </div>
        <div className="muted">Dependency edges appear once analysis is available.</div>
        {selectedEdgeData && (
          <div role="status">
            <strong>Selected:</strong> {selectedEdgeData.from.slice(2) || repoName} contains{' '}
            {selectedEdgeData.to.slice(2)}. This is folder structure, not a dependency.
          </div>
        )}
      </Panel>
      {built.truncated && (
        <Panel position="top-right" className="graph-notice" role="status">
          Showing {built.nodes.length} nodes; {built.hiddenNodes} more are hidden. Collapse folders or filter
          by language to see them.
        </Panel>
      )}
    </ReactFlow>
  )
}

export function ExplorerGraph({ repoName, theme }: { repoName: string; theme: 'dark' | 'light' }) {
  return (
    <ReactFlowProvider>
      <Canvas repoName={repoName} theme={theme} />
    </ReactFlowProvider>
  )
}
