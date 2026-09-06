import {
	Background,
	Controls,
	MiniMap,
	ReactFlow,
	ReactFlowProvider,
	useNodesInitialized,
	useReactFlow,
	type Edge,
	type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo } from 'react';
import type { TopologyResponse } from '../../../src/apiTypes';
import { buildFlowGraph, type TwinEdgeData, type TwinNodeData } from './build-flow';
import type { DetailLevel } from './hierarchy-ui';
import type { ViewMode } from './layout';
import { topologyNodeTypes } from './nodes';
import { EDGE_KIND_COLORS } from './topology-ui';
import { TopologyFlowNavigation } from './ViewModes';

type Props = {
	topology: TopologyResponse;
	mode: ViewMode;
	hierarchyFocusId?: string | null;
	detailLevel?: DetailLevel;
	isolateNodeId?: string | null;
	onSelectNode: (id: string | null) => void;
	onSelectEdge: (id: string | null) => void;
	onDrillInto?: (nodeId: string) => void;
	flowNavigation?: {
		breadcrumb: Array<{ id: string; label: string }>;
		focusId: string | null;
		canGoUp: boolean;
		onNavigate: (groupId: string) => void;
		onGoUp: () => void;
	};
	selectedNodeId?: string | null;
	selectedEdgeId?: string | null;
	highlightedNodeIds?: Set<string>;
	iconByNodeId?: Map<string, string>;
	heightClass?: string;
};

function FitOnGraphChange({ topologyKey }: { topologyKey: string }) {
	const { fitView } = useReactFlow();
	const nodesInitialized = useNodesInitialized();
	useEffect(() => {
		if (!nodesInitialized) {
			return;
		}
		const timer = window.setTimeout(() => {
			void fitView({ padding: 0.2, duration: 300 });
		}, 80);
		return () => window.clearTimeout(timer);
	}, [topologyKey, nodesInitialized, fitView]);
	return null;
}

function TopologyCanvasInner(props: Props) {
	const graph = useMemo(() => buildFlowGraph(props.topology, props.mode, {
		iconByNodeId: props.iconByNodeId,
		selectedNodeId: props.selectedNodeId,
		highlightedNodeIds: props.highlightedNodeIds,
		hierarchyFocusId: props.hierarchyFocusId,
		detailLevel: props.detailLevel,
		isolateNodeId: props.isolateNodeId,
	}), [
		props.topology,
		props.mode,
		props.iconByNodeId,
		props.selectedNodeId,
		props.highlightedNodeIds,
		props.hierarchyFocusId,
		props.detailLevel,
		props.isolateNodeId,
	]);

	const edges = useMemo(() => graph.edges.map(edge => {
		const selected = edge.id === props.selectedEdgeId;
		const internal = props.mode === 'hierarchy' && Boolean(edge.data?.internal);
		const stroke = EDGE_KIND_COLORS[edge.data?.edgeKind ?? ''] ?? EDGE_KIND_COLORS.link;
		return {
			...edge,
			className: internal ? 'twin-edge--internal' : selected ? 'twin-edge--selected' : undefined,
			style: { ...edge.style, stroke, strokeWidth: selected ? 3 : 2, opacity: internal ? 0.45 : 1 },
		};
	}), [graph.edges, props.mode, props.selectedEdgeId]);

	const onNodeClick = useCallback((_event: React.MouseEvent, node: Node<TwinNodeData>) => {
		props.onSelectNode(node.id);
		props.onSelectEdge(null);
	}, [props]);

	const onEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge<TwinEdgeData>) => {
		props.onSelectEdge(edge.id);
		props.onSelectNode(null);
	}, [props]);

	const onPaneClick = useCallback(() => {
		props.onSelectNode(null);
		props.onSelectEdge(null);
	}, [props]);

	const onNodeDoubleClick = useCallback((_event: React.MouseEvent, node: Node<TwinNodeData>) => {
		props.onDrillInto?.(node.id);
	}, [props]);

	const topologyKey = [
		props.topology.manifest_sha256,
		props.mode,
		props.hierarchyFocusId,
		props.detailLevel,
		props.isolateNodeId,
	].join('|');

	return (
		<div className={`twin-topology-canvas overflow-hidden rounded-lg border border-separator bg-background ${props.heightClass ?? 'h-[min(72vh,760px)]'}`}>
			<ReactFlow
				nodes={graph.nodes}
				edges={edges}
				nodeTypes={topologyNodeTypes}
				fitView
				colorMode="dark"
				proOptions={{ hideAttribution: true }}
				minZoom={0.2}
				maxZoom={1.8}
				onNodeClick={onNodeClick}
				onEdgeClick={onEdgeClick}
				onPaneClick={onPaneClick}
				onNodeDoubleClick={onNodeDoubleClick}
				nodesDraggable={props.mode !== 'hierarchy'}
				nodesConnectable={false}
				elementsSelectable
			>
				<Background />
				<Controls />
				<MiniMap pannable zoomable />
				<FitOnGraphChange topologyKey={topologyKey} />
				{props.flowNavigation ? <TopologyFlowNavigation {...props.flowNavigation} /> : null}
			</ReactFlow>
		</div>
	);
}

export function TopologyCanvas(props: Props): JSX.Element {
	return (
		<ReactFlowProvider>
			<TopologyCanvasInner {...props} />
		</ReactFlowProvider>
	);
}
