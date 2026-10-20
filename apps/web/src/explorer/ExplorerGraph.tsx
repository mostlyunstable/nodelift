import {
  applyNodeChanges,
  Background,
  BaseEdge,
  EdgeLabelRenderer,
  Controls,
  getBezierPath,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type EdgeProps,
  type NodeChange,
} from '@xyflow/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useExplorer } from '../state/explorer'
import { DirNode, FileNode } from './ExplorerNodes'
import {
  buildGraph,
  dirId,
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
function DependencyEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  data,
  markerEnd,
}: EdgeProps<ExplorerEdge>) {
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const conf = data?.confidence === 'heuristic' ? 'heuristic' : 'resolved'
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={`xe xe-dep xe-${conf}${data?.aggregated ? ' aggregated' : ''}${selected ? ' selected' : ''}`}
        interactionWidth={18}
      />
      {(data?.count ?? 0) > 1 && (
        <EdgeLabelRenderer>
          <span
            className="xe-label"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
          >
            {data?.count}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

const edgeTypes = { contains: ContainsEdge, dependency: DependencyEdge }

function Canvas({ repoName, theme }: { repoName: string; theme: 'dark' | 'light' }) {
  const files = useExplorer((s) => s.files)
  const expanded = useExplorer((s) => s.expanded)
  const languages = useExplorer((s) => s.languages)
  const codeOnly = useExplorer((s) => s.codeOnly)
  const selectedPath = useExplorer((s) => s.selectedPath)
  const focus = useExplorer((s) => s.focus)
  const selectedEdge = useExplorer((s) => s.selectedEdge)
  const dependencies = useExplorer((s) => s.edges)
  const diagnostics = useExplorer((s) => s.diagnostics)
  const showDeps = useExplorer((s) => s.showDeps)
  const graphTruncated = useExplorer((s) => s.graphTruncated)
  const analysisStatus = useExplorer((s) => s.revision?.analysis_status)
  const { selectFile, setSelectedEdge, reveal, toggleLanguage, clearLanguages, collapseAll, expandAll } =
    useExplorer.getState()
  const rf = useReactFlow()
  const [query, setQuery] = useState('')

  const built = useMemo(() => {
    const g = buildGraph(files, repoName, {
      expanded,
      languages,
      codeOnly,
      dependencies: showDeps ? dependencies : [],
      diagnostics,
    })
    return { ...g, nodes: layoutGraph(g.nodes, g.edges) }
  }, [files, repoName, expanded, languages, codeOnly, dependencies, diagnostics, showDeps])

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
    () =>
      built.edges.map((e) => {
        const withMarker =
          e.type === 'dependency'
            ? { ...e, markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 } }
            : e
        return e.id === selectedEdge ? { ...withMarker, selected: true } : withMarker
      }),
    [built.edges, selectedEdge],
  )

  // Frame the repository root and what is directly inside it, at a readable zoom, when a repository opens
  // or the filter changes. Expanding a folder keeps your view where it is.
  const fitKey = `${repoName}|${[...languages].join(',')}|${codeOnly}`
  const lastFit = useRef('')
  useEffect(() => {
    // wait until the repository's files have arrived (a lone root node means they have not)
    if (lastFit.current === fitKey || built.nodes.length < 2) return
    lastFit.current = fitKey
    const root = built.nodes.find((n) => n.id === dirId(''))
    if (!root) return
    // Readable zoom, with the repository root at the left and its contents filling the view
    const t = setTimeout(
      () => void rf.setCenter(root.position.x + 330, root.position.y + 24, { zoom: 0.85, duration: 200 }),
      30,
    )
    return () => clearTimeout(t)
  }, [fitKey, built.nodes, rf])

  // centre on a revealed file once its node exists
  useEffect(() => {
    if (!focus) return
    const n = built.nodes.find((x) => x.id === fileId(focus.path))
    if (n) void rf.setCenter(n.position.x + 105, n.position.y + 29, { zoom: 1, duration: 300 })
  }, [focus, built.nodes, rf])

  const hits = useMemo(() => searchFiles(files, query, 50), [files, query])
  const langs = useMemo(() => languageCounts(files).slice(0, 8), [files])
  const selectedEdgeData = built.edges.find((e) => e.id === selectedEdge)?.data
  const hasDeps = built.dependencyEdges > 0
  const nameOf = (id: string) => (id.slice(2) === '' ? repoName : id.slice(2))

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
        <div className="chips" role="group" aria-label="Show">
          <button
            className={`chip${codeOnly ? ' on' : ''}`}
            aria-pressed={codeOnly}
            onClick={() => useExplorer.getState().setCodeOnly(!codeOnly)}
            title="Hide documentation, configuration and data files"
          >
            Code only
          </button>
        </div>
        {codeOnly && (
          <div className="muted small" role="status">
            Showing source code only. Docs, configuration and data are hidden here but still in the file list.
          </div>
        )}
        <div className="chips" role="group" aria-label="Filter by language">
          {langs.map(([l, n]) => (
            <button
              key={l}
              className={`chip${languages.has(l) ? ' on' : ''}`}
              aria-pressed={languages.has(l)}
              onClick={() => toggleLanguage(l)}
            >
              {l === 'plaintext' ? 'text' : l} <span className="muted">{n}</span>
            </button>
          ))}
          {languages.size > 0 && (
            <button className="link-button" onClick={clearLanguages}>
              Clear
            </button>
          )}
          <button className="link-button" onClick={expandAll}>
            Expand all
          </button>
          <button className="link-button" onClick={collapseAll}>
            Collapse all
          </button>
        </div>
      </Panel>
      <Panel position="bottom-left" className="graph-legend" aria-label="Legend">
        <label className="legend-toggle">
          <input
            type="checkbox"
            checked={showDeps}
            onChange={(e) => useExplorer.getState().setShowDeps(e.target.checked)}
          />{' '}
          Show dependencies
        </label>
        <details className="legend-details">
          <summary>Legend</summary>
          <div>
            <svg width="28" height="8" aria-hidden="true">
              <path d="M0 4 H28" className="xe-contains" />
            </svg>{' '}
            Folder contains item (structure)
          </div>
          {hasDeps && (
            <>
              <div>
                <svg width="28" height="8" aria-hidden="true">
                  <path d="M0 4 H28" className="xe-dep xe-resolved" />
                </svg>{' '}
                Imports / references (resolved to a file)
              </div>
              <div>
                <svg width="28" height="8" aria-hidden="true">
                  <path d="M0 4 H28" className="xe-dep xe-heuristic" />
                </svg>{' '}
                Heuristic (name match, not proven)
              </div>
              <div className="muted">A number is how many relations an edge stands for.</div>
            </>
          )}
        </details>
        {analysisStatus === 'analyzing' && <div role="status">Analyzing dependencies…</div>}
        {analysisStatus === 'failed' && (
          <div role="alert">Analysis failed; dependency edges are unavailable.</div>
        )}
        {analysisStatus === 'partial' && (
          <div className="muted">Analysis hit its time budget; some files were not analyzed.</div>
        )}
        {(analysisStatus === 'done' || analysisStatus === 'partial') && !hasDeps && showDeps && (
          <div className="muted">No dependencies between the visible nodes.</div>
        )}
        {graphTruncated && (
          <div className="muted">Very large repository: only the first edges are loaded.</div>
        )}
        {selectedEdgeData?.kind === 'contains' && (
          <div role="status">
            <strong>Selected:</strong> {nameOf(selectedEdgeData.from)} contains {nameOf(selectedEdgeData.to)}.
            This is folder structure, not a dependency.
          </div>
        )}
        {selectedEdgeData?.kind === 'dependency' && (
          <div role="status" className="edge-detail">
            <strong>
              {nameOf(selectedEdgeData.from)} → {nameOf(selectedEdgeData.to)}
            </strong>
            {selectedEdgeData.aggregated && (
              <div className="muted">
                Includes files inside collapsed folders. Expand them to see each edge.
              </div>
            )}
            <ul>
              {selectedEdgeData.relations.slice(0, 8).map((r, i) => (
                <li key={i}>
                  <button
                    className="link-button"
                    onClick={() => void useExplorer.getState().goTo(r.src, r.line)}
                    title="Open the importing file at this line"
                  >
                    {r.src}:{r.line}
                  </button>{' '}
                  {r.kind.replace('_', ' ')} <code>{r.raw}</code> → <code>{r.dst}</code>
                  <div className="muted">
                    {r.confidence} · {r.provenance}
                    {r.note ? ` · ${r.note}` : ''}
                  </div>
                </li>
              ))}
            </ul>
            {selectedEdgeData.count > 8 && <div className="muted">and {selectedEdgeData.count - 8} more</div>}
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
