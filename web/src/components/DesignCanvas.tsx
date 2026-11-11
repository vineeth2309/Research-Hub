// The board of a design: boxes, groups and text that can be dragged, resized, typed into and joined with arrows.
// It shows a graph and reports each finished edit; the page that owns the graph keeps the history.
import { Background, ConnectionMode, Controls, Handle, MarkerType, NodeResizer, Panel, Position, ReactFlow, ReactFlowProvider, applyNodeChanges, useNodesInitialized, useReactFlow, type Connection, type Edge, type Node, type NodeChange, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Group, Square, Trash2, Type } from "lucide-react";
import * as React from "react";
import type { DesignEdge, DesignGraph, DesignKind, DesignNode } from "@/lib/api";
import { edgeKey, freshId, members, regroup, sides, type Mark } from "@/lib/design";
import { cn } from "@/lib/utils";
import { Tooltip } from "./ui/overlays";

type NodeData = { kind: DesignKind; label: string; detail?: string; color?: string; mark?: Mark; dim?: boolean };
type BoardNode = Node<NodeData, "design">;
interface Tools { editable: boolean; typing: string | null; rename: (id: string, label: string) => void; resize: (id: string, box: { x: number; y: number; width: number; height: number }) => void }

const Ctx = React.createContext<Tools>({ editable: false, typing: null, rename: () => undefined, resize: () => undefined });
const HANDLES = [["t", Position.Top], ["r", Position.Right], ["b", Position.Bottom], ["l", Position.Left]] as const;
const NEW_SIZE: Record<DesignKind, [number, number]> = { box: [184, 56], group: [320, 224], text: [184, 40] };
const NO_MARKS: Record<string, Mark> = {};
const tone = (name: string) => `hsl(var(--${name}))`;

function NodeView({ id, data, selected }: NodeProps<BoardNode>) {
  const tools = React.useContext(Ctx);
  const typing = tools.typing === id;
  return (
    <>
      {tools.editable && <NodeResizer isVisible={!!selected && !typing} minWidth={64} minHeight={32} onResizeEnd={(_e, box) => tools.resize(id, box)} />}
      {HANDLES.map(([side, position]) => <Handle key={side} id={side} type="source" position={position} isConnectable={tools.editable} />)}
      <div className={cn("dz-node", `dz-${data.kind}`, `dz-c-${data.color ?? "neutral"}`, selected && "dz-sel", data.mark && `dz-${data.mark}`, data.dim && "dz-dim")}>
        {typing ? (
          <textarea
            className="dz-input nodrag nopan nowheel" autoFocus defaultValue={data.label} aria-label="Text" onFocus={(e) => e.target.select()} onBlur={(e) => tools.rename(id, e.target.value)}
            onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Escape" || (e.key === "Enter" && !e.shiftKey)) { e.preventDefault(); e.currentTarget.blur(); } }}
          />
        ) : (
          <>
            <div className="dz-label">{data.label || (tools.editable && <span className="dz-hint">double-click to type</span>)}</div>
            {data.detail && data.kind !== "group" && <div className="dz-detail">{data.detail}</div>}
          </>
        )}
      </div>
    </>
  );
}
const NODE_TYPES = { design: NodeView };

export interface DesignCanvasProps {
  graph: DesignGraph;
  /** Differences to highlight, by node id or "from->to". */
  marks?: Record<string, Mark>;
  editable: boolean;
  /** A node id, or "edge:from->to". */
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** Called with the whole graph after each finished edit. */
  onChange?: (graph: DesignGraph) => void;
  /** Extra toolbar buttons while editing. */
  tools?: React.ReactNode;
  /** The view is fitted to the board again whenever this changes. */
  fitKey: string;
  theme: "light" | "dark";
}

function Board({ graph, marks = NO_MARKS, editable, selected, onSelect, onChange, tools, fitKey, theme }: DesignCanvasProps) {
  const flow = useReactFlow();
  const ready = useNodesInitialized();
  const host = React.useRef<HTMLDivElement>(null);
  const fitted = React.useRef("");
  const drag = React.useRef<{ x: number; y: number; carried: Map<string, { x: number; y: number }> } | null>(null);
  const [typing, setTyping] = React.useState<string | null>(null);
  const [nodes, setNodes] = React.useState<BoardNode[]>([]);

  // while reading, a selected node lights up what it connects to and fades the rest
  const focus = !editable && selected && !selected.startsWith("edge:") ? selected : null;
  const lit = React.useMemo(() => (focus ? new Set([focus, ...graph.edges.filter((e) => e.from === focus || e.to === focus).flatMap((e) => [e.from, e.to])]) : null), [focus, graph.edges]);

  React.useEffect(() => {
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const depth = (n: DesignNode) => { let d = 0; for (let at = n; at.group && byId.has(at.group) && d < 16; at = byId.get(at.group)!) d++; return d; };
    setNodes((now) => graph.nodes.map((n) => ({
      measured: now.find((m) => m.id === n.id)?.measured, // keep what is already measured, so nothing flickers
      // a group has the size it was drawn with; a box is at least that tall and grows with its text
      id: n.id, type: "design", position: { x: n.x, y: n.y }, width: n.w, ...(n.kind === "group" ? { height: n.h } : { initialHeight: n.h, style: { minHeight: n.h } }), zIndex: n.kind === "group" ? depth(n) : 20,
      selected: n.id === selected, draggable: editable && marks[n.id] !== "removed", className: `dz-w-${n.kind}`,
      data: { kind: n.kind, label: n.label, detail: n.detail, color: n.color, mark: marks[n.id], dim: !!lit && !lit.has(n.id) },
    })));
  }, [graph.nodes, selected, editable, marks, lit]);

  React.useEffect(() => {
    if (!ready || fitted.current === fitKey) return;
    fitted.current = fitKey;
    void flow.fitView({ padding: 0.15, maxZoom: 1.1 });
  }, [ready, fitKey, flow]);

  const edges = React.useMemo<Edge[]>(() => {
    const box = new Map(nodes.map((n) => [n.id, { x: n.position.x, y: n.position.y, w: n.width ?? 0, h: n.measured?.height ?? n.height ?? 0 }]));
    const solid = nodes.filter((n) => n.data.kind !== "group").map((n) => [n.id, box.get(n.id)!] as const);
    return graph.edges.flatMap((e) => {
      const from = box.get(e.from), to = box.get(e.to);
      if (!from || !to) return [];
      const key = edgeKey(e), mark = marks[key], picked = selected === `edge:${key}`;
      const [out, into] = sides(from, to, solid.filter(([id]) => id !== e.from && id !== e.to).map(([, b]) => b));
      const accent = picked ? "primary" : mark === "added" ? "success" : mark === "removed" ? "danger" : mark === "changed" ? "warning" : focus === e.to ? "mg-in" : focus === e.from ? "mg-out" : "";
      const color = tone(accent || "muted-foreground");
      return [{
        id: key, source: e.from, target: e.to, sourceHandle: out, targetHandle: into, label: e.label, selected: picked, zIndex: 10, interactionWidth: 18,
        className: cn(focus && !accent && "dz-dim", mark === "removed" && "dz-gone"),
        style: { stroke: color, strokeWidth: accent ? 2.2 : 1.6, strokeDasharray: e.dashed ? "6 5" : undefined },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
      }];
    });
  }, [graph.edges, nodes, marks, focus, selected]);

  const commit = (next: DesignNode[], nextEdges: DesignEdge[] = graph.edges) => onChange?.({ nodes: regroup(next), edges: nextEdges });
  const onNodesChange = (changes: NodeChange<BoardNode>[]) => setNodes((now) => applyNodeChanges(changes.filter((c) => c.type === "position" || c.type === "dimensions"), now));

  const onNodeDragStart = (_e: unknown, node: BoardNode) => {
    const inside = node.data.kind === "group" ? members(graph.nodes, node.id) : new Set<string>();
    drag.current = { x: node.position.x, y: node.position.y, carried: new Map(graph.nodes.filter((n) => inside.has(n.id)).map((n) => [n.id, { x: n.x, y: n.y }])) };
    onSelect(node.id);
  };
  const onNodeDrag = (_e: unknown, node: BoardNode) => { // a group takes what is inside it along
    const d = drag.current;
    if (!d?.carried.size) return;
    const dx = node.position.x - d.x, dy = node.position.y - d.y;
    setNodes((now) => now.map((n) => { const at = d.carried.get(n.id); return at ? { ...n, position: { x: at.x + dx, y: at.y + dy } } : n; }));
  };
  const onNodeDragStop = (_e: unknown, node: BoardNode) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const dx = Math.round(node.position.x - d.x), dy = Math.round(node.position.y - d.y);
    if (dx || dy) commit(graph.nodes.map((n) => (n.id === node.id || d.carried.has(n.id) ? { ...n, x: n.x + dx, y: n.y + dy } : n)));
  };
  const onConnect = (c: Connection) => {
    if (c.source === c.target || graph.edges.some((e) => e.from === c.source && e.to === c.target)) return;
    onChange?.({ nodes: graph.nodes, edges: [...graph.edges, { from: c.source, to: c.target }] });
    onSelect(`edge:${c.source}->${c.target}`);
  };

  const add = (kind: DesignKind) => {
    const frame = host.current!.getBoundingClientRect();
    const centre = flow.screenToFlowPosition({ x: frame.left + frame.width / 2, y: frame.top + frame.height / 2 });
    const [w, h] = NEW_SIZE[kind];
    let x = Math.round((centre.x - w / 2) / 8) * 8, y = Math.round((centre.y - h / 2) / 8) * 8;
    while (graph.nodes.some((n) => n.x === x && n.y === y)) { x += 24; y += 24; }
    const id = freshId(graph.nodes, kind);
    commit([...graph.nodes, { id, kind, label: kind === "group" ? "Group" : "", x, y, w, h }]);
    onSelect(id);
    if (kind !== "group") setTyping(id);
  };
  const remove = () => {
    if (!selected) return;
    if (selected.startsWith("edge:")) onChange?.({ nodes: graph.nodes, edges: graph.edges.filter((e) => `edge:${edgeKey(e)}` !== selected) });
    else commit(graph.nodes.filter((n) => n.id !== selected), graph.edges.filter((e) => e.from !== selected && e.to !== selected));
    onSelect(null);
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!editable || (e.target as HTMLElement).closest("input, textarea") || (e.key !== "Delete" && e.key !== "Backspace")) return;
    e.preventDefault();
    remove();
  };

  const ctx = React.useMemo<Tools>(() => ({
    editable, typing,
    rename: (id, label) => { setTyping(null); const clean = label.trim(); if (clean !== graph.nodes.find((n) => n.id === id)?.label) commit(graph.nodes.map((n) => (n.id === id ? { ...n, label: clean } : n))); },
    resize: (id, box) => commit(graph.nodes.map((n) => (n.id === id ? { ...n, x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.width), h: Math.round(box.height) } : n))),
  }), [editable, typing, graph]);

  const tool = (label: string, icon: React.ReactNode, onClick: () => void, disabled = false) => (
    <Tooltip content={label}><button type="button" className="dz-tool" onClick={onClick} disabled={disabled} aria-label={label}>{icon}</button></Tooltip>
  );
  return (
    <div ref={host} className={cn("dz h-full w-full", editable && "dz-edit")} onKeyDown={onKeyDown}>
      <Ctx.Provider value={ctx}>
        <ReactFlow
          nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} onNodesChange={onNodesChange} colorMode={theme}
          onNodeClick={(_e, n) => onSelect(n.id)} onEdgeClick={(_e, edge) => onSelect(`edge:${edge.id}`)} onPaneClick={() => onSelect(null)}
          onNodeDoubleClick={(_e, n) => { if (editable) setTyping(n.id); }} onNodeDragStart={onNodeDragStart} onNodeDrag={onNodeDrag} onNodeDragStop={onNodeDragStop} onConnect={onConnect}
          nodesDraggable={editable} nodesConnectable={editable} connectionMode={ConnectionMode.Loose} deleteKeyCode={null} selectionKeyCode={null} multiSelectionKeyCode={null}
          zoomOnDoubleClick={false} snapToGrid snapGrid={[8, 8]} minZoom={0.1} maxZoom={2.5} elevateNodesOnSelect={false}
        >
          <Background gap={16} size={1.2} />
          <Controls showInteractive={false} />
          {editable && (
            <Panel position="top-left" className="dz-bar">
              {tool("Add a box", <Square className="h-4 w-4" />, () => add("box"))}
              {tool("Add a group: boxes drawn inside it belong to it", <Group className="h-4 w-4" />, () => add("group"))}
              {tool("Add text", <Type className="h-4 w-4" />, () => add("text"))}
              <span className="dz-sep" />
              {tools}
              {tool("Delete the selection (Del)", <Trash2 className="h-4 w-4" />, remove, !selected)}
            </Panel>
          )}
          {editable && !graph.nodes.length && <Panel position="top-center" className="mt-16 rounded-md border bg-card px-3 py-2 text-[12.5px] text-muted-foreground shadow-card">Add a box, double-click it to type, and drag from a dot on its edge to another box to connect them.</Panel>}
          {Object.keys(marks).length > 0 && (
            <Panel position="top-right" className="flex gap-3 rounded-md border bg-card px-2.5 py-1.5 text-[11.5px] shadow-card">
              {(["added", "changed", "removed"] as const).map((m) => <span key={m} className="flex items-center gap-1.5"><span className={cn("h-2.5 w-2.5 rounded-sm", m === "added" ? "bg-success" : m === "changed" ? "bg-warning" : "bg-danger")} />{m}</span>)}
            </Panel>
          )}
        </ReactFlow>
      </Ctx.Provider>
    </div>
  );
}

export function DesignCanvas(props: DesignCanvasProps) {
  return <ReactFlowProvider><Board {...props} /></ReactFlowProvider>;
}
