import { useCallback, useEffect, useMemo, useRef } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type NodeMouseHandler,
  type NodeTypes,
} from '@xyflow/react';
import type { FlowSpec } from '../flows/types';
import { LayerNode, type NodeState, type WardressNode } from './LayerNode';
import { accentOf } from '../lib/accent';

const nodeTypes: NodeTypes = { wardress: LayerNode };

interface Props {
  flow: FlowSpec;
  step: number; // -1 before start
  gateSkipped: boolean; // content-hash identical → gated layers skip
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

// A gated node is skipped only when the hash matched AND this flow has a gate.
function isSkipped(gateRole: string, gateSkipped: boolean): boolean {
  return gateSkipped && gateRole === 'gated';
}

function computeNodeState(
  nodeStep: number,
  gateRole: string,
  step: number,
  gateSkipped: boolean,
): NodeState {
  if (isSkipped(gateRole, gateSkipped)) return 'skipped';
  if (step < 0 || nodeStep > step) return 'pending';
  if (nodeStep === step) return 'active';
  return 'done';
}

function CanvasInner({ flow, step, gateSkipped, selectedId, onSelect }: Props) {
  const { fitView } = useReactFlow();
  const reduceMotion = useRef(
    typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );

  const nodes: WardressNode[] = useMemo(
    () =>
      flow.nodes.map((spec) => ({
        id: spec.id,
        type: 'wardress',
        position: spec.position,
        data: {
          spec,
          state: computeNodeState(spec.step, spec.gateRole, step, gateSkipped),
          selected: spec.id === selectedId,
        },
        selectable: true,
        draggable: false,
      })),
    [flow, step, gateSkipped, selectedId],
  );

  const edges: Edge[] = useMemo(
    () =>
      flow.edges.map((e) => {
        const skipped = gateSkipped && e.branch === 'gated';
        // An edge "flows" once the step reaches it and it isn't skipped.
        const reached = step >= e.step && !skipped;
        const isCurrent = step === e.step && !skipped;
        const { color } = accentOf(e.accent ?? 'neutral');

        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: 'smoothstep',
          animated: isCurrent && !reduceMotion.current,
          style: {
            stroke: skipped ? 'rgba(255,255,255,0.06)' : reached ? color : 'var(--color-hairline-strong)',
            strokeWidth: reached ? 2 : 1.25,
            strokeDasharray: skipped ? '4 4' : undefined,
            opacity: skipped ? 0.4 : reached ? 1 : 0.55,
            transition: 'stroke 400ms ease, opacity 400ms ease, stroke-width 400ms ease',
          },
        } satisfies Edge;
      }),
    [flow, step, gateSkipped],
  );

  // Frame the whole graph on flow change (and initial mount).
  useEffect(() => {
    const id = window.setTimeout(
      () => fitView({ padding: 0.16, duration: reduceMotion.current ? 0 : 600 }),
      60,
    );
    return () => window.clearTimeout(id);
  }, [flow.id, fitView]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_, node) => onSelect(node.id === selectedId ? null : node.id),
    [onSelect, selectedId],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      onPaneClick={() => onSelect(null)}
      fitView
      fitViewOptions={{ padding: 0.16 }}
      minZoom={0.4}
      maxZoom={1.6}
      proOptions={{ hideAttribution: true }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      panOnScroll
      zoomOnScroll={false}
      zoomOnDoubleClick={false}
    >
      <Background variant={BackgroundVariant.Dots} gap={26} size={1} color="rgba(255,255,255,0.05)" />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}

export function FlowCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}
