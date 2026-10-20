import {
  BaseEdge,
  Background,
  Controls,
  EdgeLabelRenderer,
  getBezierPath,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type EdgeProps,
  type ReactFlowInstance,
} from '@xyflow/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useExplorer } from '../state/explorer'
import { CardNode, FileNode, FolderTile } from './ExplorerNodes'
import {
  absoluteRect,
  buildGraph,
  dirId,
  fileId,
  languageCounts,
  viewportFor,
  type DepMode,
  type ExplorerEdge,
  type ExplorerNode,
} from './graph'
import { searchFiles } from './tree'

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
  const [path, lx, ly] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    curvature: 0.4,
  })
  const kind = data?.confidence === 'heuristic' ? 'heuristic' : 'resolved'
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={`xe xe-dep xe-${kind} dir-${data?.direction || 'none'}${data?.aggregated ? ' aggregated' : ''}${selected ? ' selected' : ''}`}
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

const nodeTypes = { file: FileNode, folder: FolderTile, card: CardNode }
const edgeTypes = { dependency: DependencyEdge }

const DEP_MODES: [DepMode, string, string][] = [
  ['selected', 'Selected file', 'Show what the selected file imports and what imports it'],
  ['folders', 'Folders', 'Show the strongest links between the top-level folders'],
  ['all', 'All', 'Show every dependency line (can be crowded)'],
  ['off', 'Off', 'Show no dependency lines'],
]

type ShowOpts = { minZoom?: number; maxZoom?: number; margin?: number; duration?: number }

/** Pan and zoom so the node `id` (a card or tile) fills the window as well as readability allows. */
function showNode(
  rf: ReactFlowInstance,
  el: HTMLElement | null,
  nodes: ExplorerNode[],
  id: string,
  o: ShowOpts = {},
) {
  const rect = absoluteRect(nodes, id)
  if (!el || !rect) return
  void rf.setViewport(viewportFor(rect, el.clientWidth, el.clientHeight, o.minZoom, o.maxZoom, o.margin), {
    duration: o.duration ?? 200,
  })
}

function Canvas({ repoName, theme }: { repoName: string; theme: 'dark' | 'light' }) {
  const files = useExplorer((s) => s.files)
  const expanded = useExplorer((s) => s.expanded)
  const languages = useExplorer((s) => s.languages)
  const codeOnly = useExplorer((s) => s.codeOnly)
  const selectedPath = useExplorer((s) => s.selectedPath)
  const focus = useExplorer((s) => s.focus)
  const opened = useExplorer((s) => s.opened)
  const selectedEdge = useExplorer((s) => s.selectedEdge)
  const dependencies = useExplorer((s) => s.edges)
  const diagnostics = useExplorer((s) => s.diagnostics)
  const depMode = useExplorer((s) => s.depMode)
  const graphTruncated = useExplorer((s) => s.graphTruncated)
  const analysisStatus = useExplorer((s) => s.revision?.analysis_status)
  const { setSelectedEdge, reveal, toggleLanguage, clearLanguages, collapseAll, expandAll } =
    useExplorer.getState()
  const rf = useReactFlow()
  const canvas = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')

  const built = useMemo(
    () =>
      buildGraph(files, repoName, {
        expanded,
        languages,
        codeOnly,
        dependencies,
        diagnostics,
        depMode,
        selectedPath,
      }),
    [files, repoName, expanded, languages, codeOnly, dependencies, diagnostics, depMode, selectedPath],
  )

  const nodes: ExplorerNode[] = useMemo(
    () => built.nodes.map((n) => (n.id === fileId(selectedPath ?? '\0') ? { ...n, selected: true } : n)),
    [built.nodes, selectedPath],
  )
  const edges: ExplorerEdge[] = useMemo(
    () =>
      built.edges.map((e) => ({
        ...e,
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
        selected: e.id === selectedEdge,
      })),
    [built.edges, selectedEdge],
  )

  // Show the whole repository card (or the top of it, if it is too big to read at once) when a repository opens
  // or the filter changes.
  const fitKey = `${repoName}|${[...languages].join(',')}|${codeOnly}`
  const lastFit = useRef('')
  useEffect(() => {
    if (lastFit.current === fitKey || built.nodes.length < 2) return
    lastFit.current = fitKey
    showNode(rf, canvas.current, built.nodes, dirId(''), { minZoom: 0.55, duration: 0 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, built.nodes.length])

  // When the user opens a folder, bring the whole of it into view (not when a repository opens with folders open).
  useEffect(() => {
    if (!opened || lastFit.current === '') return
    const t = setTimeout(
      () =>
        showNode(rf, canvas.current, built.nodes, dirId(opened.path), {
          minZoom: 0.55,
          margin: 40,
          duration: 250,
        }),
      30,
    )
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened])

  // Centre on a revealed file once its tile exists.
  useEffect(() => {
    if (!focus) return
    const r = absoluteRect(built.nodes, fileId(focus.path))
    const el = canvas.current
    if (!r || !el) return
    void rf.setViewport(
      { x: el.clientWidth / 2 - (r.x + r.width / 2), y: el.clientHeight / 2 - (r.y + r.height / 2), zoom: 1 },
      { duration: 300 },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus])

  const hits = useMemo(() => searchFiles(files, query, 50), [files, query])
  const langs = useMemo(() => languageCounts(files).slice(0, 8), [files])
  const selectedEdgeData = built.edges.find((e) => e.id === selectedEdge)?.data
  const hasDeps = built.dependencyEdges > 0
  const nameOf = (id: string) => (id.slice(2) === '' ? repoName : id.slice(2))

  return (
    <div className="graph-wrap">
      <div className="graph-toolbar" role="group" aria-label="Graph tools">
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
        <div className="chips" role="group" aria-label="Dependency lines">
          <span className="chips-label">Lines</span>
          {DEP_MODES.map(([mode, label, tip]) => (
            <button
              key={mode}
              className={`chip${depMode === mode ? ' on' : ''}`}
              aria-pressed={depMode === mode}
              title={tip}
              onClick={() => useExplorer.getState().setDepMode(mode)}
            >
              {label}
            </button>
          ))}
        </div>
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
        {codeOnly && (
          <div className="muted small toolbar-note" role="status">
            Showing source code only. Docs, configuration and data are hidden here but still in the file list.
          </div>
        )}
        {depMode === 'selected' && !selectedPath && (
          <div className="muted small toolbar-note">
            Select a file to see what it imports and what imports it.
          </div>
        )}
      </div>
      <div className="graph-canvas" ref={canvas}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onEdgeClick={(_, e) => setSelectedEdge(e.id)}
          onPaneClick={() => setSelectedEdge(null)}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          zoomOnDoubleClick={false}
          aria-label="Repository graph"
          deleteKeyCode={null}
          colorMode={theme}
          minZoom={0.1}
        >
          <Background gap={22} size={1.2} />
          <Controls showInteractive={false} />
          {built.nodes.length > 40 && (
            <MiniMap
              pannable
              zoomable
              nodeStrokeWidth={0}
              nodeColor={(n) => (n.type === 'card' ? 'var(--border-strong)' : 'var(--accent)')}
            />
          )}
          <Panel position="bottom-left" className="graph-legend" aria-label="Legend">
            <details className="legend-details">
              <summary>Legend</summary>
              <div>Cards are folders; tiles are files. Click a ▸ folder tile to open it.</div>
              <div>
                <svg width="28" height="8" aria-hidden="true">
                  <path d="M0 4 H28" className="xe-dep dir-out" />
                </svg>{' '}
                What the selected file imports or calls
              </div>
              <div>
                <svg width="28" height="8" aria-hidden="true">
                  <path d="M0 4 H28" className="xe-dep dir-in" />
                </svg>{' '}
                What imports the selected file
              </div>
              <div>
                <svg width="28" height="8" aria-hidden="true">
                  <path d="M0 4 H28" className="xe-dep xe-heuristic" />
                </svg>{' '}
                Heuristic (name match, not proven)
              </div>
              <div className="muted">A number is how many relations a line stands for.</div>
            </details>
            {analysisStatus === 'analyzing' && <div role="status">Analyzing dependencies…</div>}
            {analysisStatus === 'failed' && (
              <div role="alert">Analysis failed; dependency lines are unavailable.</div>
            )}
            {analysisStatus === 'partial' && (
              <div className="muted">Analysis hit its time budget; some files were not analyzed.</div>
            )}
            {(analysisStatus === 'done' || analysisStatus === 'partial') &&
              !hasDeps &&
              depMode !== 'off' &&
              depMode !== 'selected' && (
                <div className="muted">No dependencies between the visible items.</div>
              )}
            {depMode === 'selected' &&
              selectedPath &&
              !hasDeps &&
              (analysisStatus === 'done' || analysisStatus === 'partial') && (
                <div className="muted">This file has no resolved dependencies in the repository.</div>
              )}
            {graphTruncated && (
              <div className="muted">Very large repository: only the first relations are loaded.</div>
            )}
            {built.hiddenDependencyEdges > 0 && (
              <div className="muted">{built.hiddenDependencyEdges} more lines are not drawn.</div>
            )}
            {selectedEdgeData && (
              <div role="status" className="edge-detail">
                <strong>
                  {nameOf(selectedEdgeData.from)} → {nameOf(selectedEdgeData.to)}
                </strong>
                {selectedEdgeData.aggregated && (
                  <div className="muted">
                    Includes files inside collapsed folders. Open them to see each line.
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
                {selectedEdgeData.count > 8 && (
                  <div className="muted">and {selectedEdgeData.count - 8} more</div>
                )}
              </div>
            )}
          </Panel>
          {built.truncated && (
            <Panel position="top-right" className="graph-notice" role="status">
              Showing {built.nodes.length} items; {built.hiddenNodes} more are hidden. Collapse folders or
              filter by language to see them.
            </Panel>
          )}
        </ReactFlow>
      </div>
    </div>
  )
}

export function ExplorerGraph({ repoName, theme }: { repoName: string; theme: 'dark' | 'light' }) {
  return (
    <ReactFlowProvider>
      <Canvas repoName={repoName} theme={theme} />
    </ReactFlowProvider>
  )
}
