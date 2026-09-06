import type { Edge, Node } from '@xyflow/react';
import type {
	FrameBoundaryLink,
	HierarchyGroup,
	TopologyEdge,
	TopologyNode,
	TopologyResponse,
} from '../../../src/apiTypes';
import { childGroups, defaultFocusId, focusGroup, hierarchyIndex } from './hierarchy-layout';
import { type DetailLevel, detailLevelSpec, hierarchyGroupAccent } from './hierarchy-ui';
import {
	DEFAULT_BLOCK_GAP,
	DEFAULT_NODE_GAP,
	type LayoutSpacing,
	type ViewMode,
	groupLabel,
	groupMeta,
	groupStyle,
	layoutNodes,
	parentForNode,
} from './layout';
import { buildTopologyModel, coordinationHostEndpointSide, stagingLaneForGroup, type TopologyModel } from './topology-model';
import { DEFAULT_IN_HANDLE, DEFAULT_OUT_HANDLE, edgeStroke, nodeAccent } from './topology-ui';

export type TwinNodeData = {
	label: string;
	nodeType: string;
	componentClass?: string | null;
	domain?: string | null;
	sourceFile?: string;
	accent: string;
	iconUrl?: string;
	isGroup?: boolean;
	deploymentRole?: string | null;
	groupKind?: string | null;
	packageId?: string | null;
	compact?: boolean;
	nodeWidth?: number;
	highlighted?: boolean;
	frameDepth?: number;
	nested?: boolean;
	collapsedSummary?: string | null;
	minimalFrame?: boolean;
	parentFrameId?: string | null;
};

export type TwinEdgeData = {
	edgeKind: string;
	sourcePort?: string | null;
	targetPort?: string | null;
	via?: string | null;
	internal?: boolean;
};

export type BuildFlowOptions = {
	iconByNodeId?: Map<string, string>;
	selectedNodeId?: string | null;
	highlightedNodeIds?: Set<string>;
	hierarchyFocusId?: string | null;
	detailLevel?: DetailLevel;
	isolateNodeId?: string | null;
};

function edgeProps(e: TopologyEdge): Partial<Edge<TwinEdgeData>> {
	return {
		type: 'smoothstep',
		animated: e.edge_kind === 'digital' || e.edge_kind === 'software',
		style: { stroke: edgeStroke(e), strokeWidth: 2 },
		sourceHandle: DEFAULT_OUT_HANDLE,
		targetHandle: DEFAULT_IN_HANDLE,
		data: {
			edgeKind: e.edge_kind,
			sourcePort: e.source_port,
			targetPort: e.target_port,
			via: e.via,
		},
	};
}

function resolveLayoutSpacing(): LayoutSpacing {
	return { blockGap: DEFAULT_BLOCK_GAP, nodeGap: DEFAULT_NODE_GAP };
}

export function buildFlowGraph(
	topology: TopologyResponse,
	mode: ViewMode,
	options: BuildFlowOptions = {},
): { nodes: Node<TwinNodeData>[]; edges: Edge<TwinEdgeData>[] } {
	const { iconByNodeId, selectedNodeId, highlightedNodeIds, hierarchyFocusId } = options;

	if (mode === 'hierarchy' && topology.hierarchy?.length) {
		return buildNestedHierarchyGraph(topology, hierarchyFocusId, options);
	}

	const groups = topology.groups ?? [];
	const { positions, visible, groupIds, groupSizes } = layoutNodes(topology.nodes, mode, groups, resolveLayoutSpacing());
	const visibleIds = new Set(visible.map(n => n.id));
	const edgeEndpointIds = new Set([...visibleIds, ...groupIds]);
	const nodeById = new Map(topology.nodes.map(n => [n.id, n]));
	const rfNodes: Node<TwinNodeData>[] = [];

	for (const groupId of groupIds) {
		const pos = positions.get(groupId);
		if (!pos) {
			continue;
		}
		const hasChildren = topology.nodes.some(n => parentForNode(n) === groupId && visibleIds.has(n.id));
		if (mode === 'full' && hasChildren) {
			const { width, height } = groupStyle(groupId, groupSizes);
			const subNode = nodeById.get(groupId);
			const groupInfo = groupMeta(groupId, groups);
			rfNodes.push({
				id: groupId,
				type: 'twinGroup',
				position: pos,
				selected: selectedNodeId === groupId,
				data: {
					label: groupLabel(groupId, groups),
					nodeType: 'group',
					accent: subNode ? nodeAccent(subNode) : '#64748b',
					iconUrl: iconByNodeId?.get(groupId),
					isGroup: true,
					deploymentRole: groupInfo?.deployment_role ?? subNode?.deployment_role ?? null,
					groupKind: groupInfo?.group_kind ?? groupInfo?.deployment_role ?? 'subsystem',
					highlighted: highlightedNodeIds?.has(groupId) ?? selectedNodeId === groupId,
				},
				style: { width, height },
				selectable: true,
				draggable: false,
				zIndex: 0,
			});
		}
	}

	for (const node of visible) {
		const pos = positions.get(node.id);
		if (!pos) {
			continue;
		}
		const parent = mode === 'full' ? parentForNode(node) : undefined;
		const parentVisible = parent && groupIds.has(parent) && rfNodes.some(n => n.id === parent);
		rfNodes.push({
			id: node.id,
			type: 'twinNode',
			position: pos,
			parentId: parentVisible ? parent : undefined,
			extent: parentVisible ? 'parent' : undefined,
			selected: selectedNodeId === node.id,
			zIndex: parentVisible ? 10 : 15,
			data: {
				label: node.label,
				nodeType: node.node_type,
				componentClass: node.component_class,
				domain: node.domain,
				sourceFile: node.source_file,
				accent: nodeAccent(node),
				iconUrl: iconByNodeId?.get(node.id),
				isGroup: false,
				highlighted: (highlightedNodeIds?.has(node.id) ?? false) || selectedNodeId === node.id,
			},
			draggable: true,
		});
	}

	const rfEdges = topology.edges
		.filter(e => edgeEndpointIds.has(e.source) && edgeEndpointIds.has(e.target))
		.map(e => ({ id: e.id, source: e.source, target: e.target, ...edgeProps(e) }));

	if (mode === 'system') {
		const resolveBoundary = (id: string): string | null => {
			const n = nodeById.get(id);
			if (!n) {
				return null;
			}
			if (n.node_type === 'subsystem' || n.node_type === 'channel') {
				return n.id;
			}
			if (n.subsystem && edgeEndpointIds.has(n.subsystem)) {
				return n.subsystem;
			}
			const parent = parentForNode(n);
			if (parent && edgeEndpointIds.has(parent)) {
				return parent;
			}
			return null;
		};
		const lifted = new Map<string, Edge<TwinEdgeData>>();
		for (const e of topology.edges) {
			const src = resolveBoundary(e.source);
			const tgt = resolveBoundary(e.target);
			if (!src || !tgt || src === tgt || !edgeEndpointIds.has(src) || !edgeEndpointIds.has(tgt)) {
				continue;
			}
			const id = `${src}~${tgt}~${e.edge_kind}~${e.source_port ?? ''}~${e.target_port ?? ''}`;
			if (!lifted.has(id)) {
				lifted.set(id, { id, source: src, target: tgt, ...edgeProps(e) });
			}
		}
		return { nodes: rfNodes, edges: Array.from(lifted.values()) };
	}

	return { nodes: rfNodes, edges: rfEdges };
}

function collectFlatMembers(
	index: Map<string, HierarchyGroup>,
	groupId: string,
	flatNodeIds: Set<string>,
	memo: Map<string, Set<string>>,
): Set<string> {
	const cached = memo.get(groupId);
	if (cached) {
		return cached;
	}
	const acc = new Set<string>();
	memo.set(groupId, acc);
	if (flatNodeIds.has(groupId)) {
		acc.add(groupId);
	}
	const group = index.get(groupId);
	if (group) {
		for (const memberId of group.member_ids ?? []) {
			if (flatNodeIds.has(memberId)) {
				acc.add(memberId);
			}
		}
		for (const childId of group.children ?? []) {
			for (const flatId of collectFlatMembers(index, childId, flatNodeIds, memo)) {
				acc.add(flatId);
			}
		}
	}
	return acc;
}

const N_FRAME_HEADER = 30;
const N_PAD_X = 16;
const N_PAD_TOP = N_FRAME_HEADER + 12;
const N_PAD_BOTTOM = 16;
const N_LEAF_W = 162;
const N_LEAF_H = 84;
const N_MIN_FRAME_W = 184;
const N_MIN_FRAME_H = 78;

type FrameLayout = {
	header: number;
	padX: number;
	padTop: number;
	padBottom: number;
	groupGap: number;
	nodeGap: number;
	blockLaneGap: number;
	minimal: boolean;
};

type HierarchyLayoutSpacing = { groupGap: number; nodeGap: number };

function frameLayoutFor(kind: string, spacing?: HierarchyLayoutSpacing): FrameLayout {
	const groupGap = spacing?.groupGap ?? DEFAULT_BLOCK_GAP;
	const nodeGap = spacing?.nodeGap ?? DEFAULT_NODE_GAP;
	if (kind === 'domain') {
		return { header: 14, padX: 8, padTop: 20, padBottom: 8, groupGap: 10, nodeGap: 10, blockLaneGap: 14, minimal: true };
	}
	return {
		header: N_FRAME_HEADER,
		padX: N_PAD_X + Math.round(groupGap * 0.15),
		padTop: N_PAD_TOP,
		padBottom: N_PAD_BOTTOM + Math.round(groupGap * 0.2),
		groupGap,
		nodeGap,
		blockLaneGap: Math.round(groupGap * 1.35),
		minimal: false,
	};
}

type LaidOut = {
	id: string;
	kind: string;
	label: string;
	accent: string;
	packageId?: string | null;
	isLeaf: boolean;
	depth: number;
	width: number;
	height: number;
	x: number;
	y: number;
	node?: TopologyNode;
	collapsedSummary?: string | null;
	minimal?: boolean;
	flatMembers: Set<string>;
	children: LaidOut[];
};

type NestedContext = {
	hierarchy: HierarchyGroup[];
	index: Map<string, HierarchyGroup>;
	nodeById: Map<string, TopologyNode>;
	flatNodeIds: Set<string>;
	memo: Map<string, Set<string>>;
	frameMaxDepth: number;
	renderLeaves: boolean;
	isolateNodeId: string | null;
	spacing: HierarchyLayoutSpacing;
};

function layoutLeaf(node: TopologyNode, depth: number): LaidOut {
	return {
		id: node.id,
		kind: 'component',
		label: node.label,
		accent: nodeAccent(node),
		isLeaf: true,
		depth,
		width: N_LEAF_W,
		height: N_LEAF_H,
		x: 0,
		y: 0,
		node,
		flatMembers: new Set([node.id]),
		children: [],
	};
}

function layoutGroupLeaf(group: HierarchyGroup, depth: number, ctx: NestedContext): LaidOut {
	return {
		id: group.id,
		kind: 'component',
		label: group.label,
		accent: hierarchyGroupAccent(group),
		packageId: group.package_id,
		isLeaf: true,
		depth,
		width: N_LEAF_W,
		height: N_LEAF_H,
		x: 0,
		y: 0,
		collapsedSummary: null,
		flatMembers: collectFlatMembers(ctx.index, group.id, ctx.flatNodeIds, ctx.memo),
		children: [],
	};
}

function sortNodeChildren(group: HierarchyGroup, children: LaidOut[]): LaidOut[] {
	if (group.group_kind !== 'qkd_node') {
		return children;
	}
	const rank = (child: LaidOut) => {
		if (child.kind === 'qkd_device') {
			return 0;
		}
		if (child.kind === 'kms' || child.kind === 'network_coordination') {
			return 2;
		}
		return 1;
	};
	return [...children].sort((a, b) => rank(a) - rank(b));
}

function gapBetweenChildren(a: LaidOut, b: LaidOut, layout: FrameLayout): number {
	return a.isLeaf && b.isLeaf ? layout.nodeGap : layout.groupGap;
}

function positionVerticalStack(children: LaidOut[], layout: FrameLayout): { width: number; height: number } {
	let y = layout.padTop;
	let maxW = 0;
	let lastGap = 0;
	for (let i = 0; i < children.length; i++) {
		const child = children[i];
		const next = children[i + 1];
		child.x = layout.padX;
		child.y = y;
		lastGap = next ? gapBetweenChildren(child, next, layout) : child.isLeaf ? layout.nodeGap : layout.groupGap;
		y += child.height + lastGap;
		maxW = Math.max(maxW, child.width);
	}
	return {
		width: Math.max(layout.minimal ? 140 : N_MIN_FRAME_W, layout.padX * 2 + maxW),
		height: (children.length ? y - lastGap : layout.padTop) + layout.padBottom,
	};
}

function positionSystemStaging(
	children: LaidOut[],
	layout: FrameLayout,
	groupsById: Map<string, HierarchyGroup>,
): { width: number; height: number } {
	const laneOf = (child: LaidOut) => String(stagingLaneForGroup(groupsById.get(child.id) ?? { id: child.id, label: child.label, group_kind: child.kind }));
	const source = children.find(c => laneOf(c) === 'center');
	const left = children.find(c => laneOf(c) === 'left');
	const right = children.find(c => laneOf(c) === 'right');
	const others = children.filter(c => {
		const lane = laneOf(c);
		return lane !== 'center' && lane !== 'left' && lane !== 'right';
	});
	let y = layout.padTop;
	const laneGap = layout.blockLaneGap;
	const pairW = (left?.width ?? 0) + (left && right ? laneGap : 0) + (right?.width ?? 0);
	const topW = Math.max(source?.width ?? 0, pairW);
	if (source) {
		source.x = layout.padX + (topW - source.width) / 2;
		source.y = y;
		y += source.height + layout.groupGap;
	}
	if (left || right) {
		const offset = layout.padX + (topW - pairW) / 2;
		if (left) {
			left.x = offset;
			left.y = y;
		}
		if (right) {
			right.x = offset + (left?.width ?? 0) + (left ? laneGap : 0);
			right.y = y;
		}
		y += Math.max(left?.height ?? 0, right?.height ?? 0) + layout.groupGap;
	}
	let maxW = topW;
	for (const other of others) {
		other.x = layout.padX + (topW - other.width) / 2;
		other.y = y;
		y += other.height + layout.groupGap;
		maxW = Math.max(maxW, other.width);
	}
	return {
		width: Math.max(N_MIN_FRAME_W, layout.padX * 2 + maxW),
		height: (children.length ? y - layout.groupGap : layout.padTop) + layout.padBottom,
	};
}

function positionGrid(children: LaidOut[], layout: FrameLayout, columns: number): { width: number; height: number } {
	const cols = Math.max(1, Math.min(columns, children.length || 1));
	const colW = Math.max(N_LEAF_W, ...children.map(c => c.width));
	const rowH = Math.max(N_LEAF_H, ...children.map(c => c.height));
	children.forEach((child, i) => {
		child.x = layout.padX + (i % cols) * (colW + layout.nodeGap);
		child.y = layout.padTop + Math.floor(i / cols) * (rowH + layout.nodeGap);
	});
	const rows = Math.ceil(children.length / cols);
	return {
		width: layout.padX * 2 + cols * colW + (cols - 1) * layout.nodeGap,
		height: layout.padTop + rows * rowH + Math.max(0, rows - 1) * layout.nodeGap + layout.padBottom,
	};
}

function positionChildren(
	group: HierarchyGroup,
	children: LaidOut[],
	layout: FrameLayout,
	groupsById: Map<string, HierarchyGroup>,
): { width: number; height: number } {
	const ordered = sortNodeChildren(group, children);
	if (group.group_kind === 'qkd_system') {
		return positionSystemStaging(ordered, layout, groupsById);
	}
	if (group.group_kind === 'software_group') {
		return positionGrid(ordered, layout, 3);
	}
	return positionVerticalStack(ordered, layout);
}

function layoutFrame(group: HierarchyGroup, depth: number, ctx: NestedContext): LaidOut {
	const { index, nodeById, flatNodeIds, memo, frameMaxDepth, renderLeaves } = ctx;
	const flatMembers = collectFlatMembers(index, group.id, flatNodeIds, memo);
	const layout = frameLayoutFor(group.group_kind, ctx.spacing);
	const frameKids = depth < frameMaxDepth ? childGroups(ctx.hierarchy, group.id) : [];
	let children: LaidOut[] = [];
	if (group.group_kind === 'software_group') {
		if (renderLeaves) {
			children = frameKids
				.filter(g => !ctx.isolateNodeId || g.id === ctx.isolateNodeId)
				.map(g => layoutGroupLeaf(g, depth + 1, ctx));
		}
	} else if (frameKids.length > 0) {
		children = frameKids.map(g => layoutFrame(g, depth + 1, ctx));
	}
	if (renderLeaves && group.group_kind !== 'software_group') {
		const leaves = (group.member_ids ?? [])
			.filter(id => !index.has(id))
			.filter(id => !ctx.isolateNodeId || id === ctx.isolateNodeId)
			.map(id => nodeById.get(id))
			.filter((n): n is TopologyNode => Boolean(n));
		children = children.concat(leaves.map(n => layoutLeaf(n, depth + 1)));
	}
	const base = {
		id: group.id,
		kind: group.group_kind,
		label: group.label,
		accent: hierarchyGroupAccent(group),
		packageId: group.package_id,
		isLeaf: false as const,
		depth,
		x: 0,
		y: 0,
		flatMembers,
		minimal: layout.minimal,
	};
	if (children.length === 0) {
		const count = group.group_kind === 'software_group' ? (group.children ?? []).length : flatMembers.size;
		return {
			...base,
			width: layout.minimal ? 140 : N_MIN_FRAME_W,
			height: layout.minimal ? 52 : N_MIN_FRAME_H,
			collapsedSummary: count > 0 ? `${count} component${count === 1 ? '' : 's'}` : null,
			children: [],
		};
	}
	const size = positionChildren(group, children, layout, index);
	return { ...base, width: size.width, height: size.height, children };
}

function isNestedPair(a: LaidOut, b: LaidOut): boolean {
	const [small, big] = a.flatMembers.size <= b.flatMembers.size ? [a, b] : [b, a];
	if (small.flatMembers.size === 0) {
		return false;
	}
	for (const id of small.flatMembers) {
		if (!big.flatMembers.has(id)) {
			return false;
		}
	}
	return true;
}

function buildFrameBoundaryEdges(
	links: FrameBoundaryLink[],
	framesById: Map<string, LaidOut>,
): Edge<TwinEdgeData>[] {
	const edges: Edge<TwinEdgeData>[] = [];
	for (const link of links) {
		const sourceFrame = framesById.get(link.source_frame);
		const targetFrame = framesById.get(link.target_frame);
		if (!sourceFrame || !targetFrame || sourceFrame.id === targetFrame.id) {
			continue;
		}
		edges.push({
			id: link.id,
			source: sourceFrame.id,
			target: targetFrame.id,
			type: 'smoothstep',
			sourceHandle: DEFAULT_OUT_HANDLE,
			targetHandle: DEFAULT_IN_HANDLE,
			animated: link.edge_kind === 'digital' || link.edge_kind === 'software',
			style: { stroke: edgeStroke({ edge_kind: link.edge_kind }), strokeWidth: 2 },
			data: { edgeKind: link.edge_kind, sourcePort: link.source_port, targetPort: link.target_port, via: link.via ?? link.channel_id, internal: false },
		});
	}
	return edges;
}

function buildNestedEdges(
	topology: TopologyResponse,
	bestByFlat: Map<string, LaidOut>,
	nodeFrameBySide: Map<string, LaidOut>,
	framesById: Map<string, LaidOut>,
	model: TopologyModel,
): Edge<TwinEdgeData>[] {
	const nodeById = new Map(topology.nodes.map(n => [n.id, n]));
	const channelIds = new Set(topology.nodes.filter(n => n.node_type === 'channel').map(n => n.id));
	const resolve = (flatId: string): LaidOut | null => {
		const direct = bestByFlat.get(flatId);
		if (direct) {
			return direct;
		}
		if (flatId === 'network_coordination') {
			const hostSide = coordinationHostEndpointSide(model);
			return hostSide ? nodeFrameBySide.get(hostSide) ?? null : null;
		}
		const flatNode = nodeById.get(flatId);
		const side = flatNode?.endpoint_side ?? model.groupsById.get(flatId)?.endpoint_side ?? null;
		return side ? nodeFrameBySide.get(side) ?? null : null;
	};
	const realEdges: { source: string; target: string; edge: TopologyEdge }[] = [];
	for (const edge of topology.edges) {
		if (channelIds.has(edge.source) || channelIds.has(edge.target)) {
			continue;
		}
		realEdges.push({ source: edge.source, target: edge.target, edge });
	}
	for (const channelId of channelIds) {
		const ins = topology.edges.filter(e => e.target === channelId);
		const outs = topology.edges.filter(e => e.source === channelId);
		for (const incoming of ins) {
			for (const outgoing of outs) {
				realEdges.push({ source: incoming.source, target: outgoing.target, edge: outgoing });
			}
		}
	}
	const lifted = new Map<string, Edge<TwinEdgeData>>();
	for (const { source, target, edge } of realEdges) {
		const src = resolve(source);
		const tgt = resolve(target);
		if (!src || !tgt || src.id === tgt.id || isNestedPair(src, tgt)) {
			continue;
		}
		const id = `${src.id}~${tgt.id}~${edge.edge_kind}~${edge.source_port ?? ''}~${edge.target_port ?? ''}`;
		if (lifted.has(id)) {
			continue;
		}
		const props = edgeProps(edge);
		lifted.set(id, {
			id,
			source: src.id,
			target: tgt.id,
			...props,
			data: { ...(props.data as TwinEdgeData), internal: true },
		});
	}
	const edges = Array.from(lifted.values());
	if (topology.frame_links?.length) {
		edges.push(...buildFrameBoundaryEdges(topology.frame_links, framesById));
		return edges;
	}
	for (const link of model.interNodeLinks) {
		const sourceFrame = framesById.get(link.sourceFrameId)
			?? (link.sourceEndpointSide ? nodeFrameBySide.get(link.sourceEndpointSide) : null)
			?? bestByFlat.get(link.sourceNodeId);
		const targetFrame = framesById.get(link.targetFrameId)
			?? (link.targetEndpointSide ? nodeFrameBySide.get(link.targetEndpointSide) : null)
			?? bestByFlat.get(link.targetNodeId);
		if (!sourceFrame || !targetFrame || sourceFrame.id === targetFrame.id) {
			continue;
		}
		if (!link.sourcePort && !link.targetPort) {
			continue;
		}
		edges.push({
			id: `inter_node|${sourceFrame.id}~${targetFrame.id}~${link.sourcePort ?? ''}`,
			source: sourceFrame.id,
			target: targetFrame.id,
			type: 'smoothstep',
			sourceHandle: DEFAULT_OUT_HANDLE,
			targetHandle: DEFAULT_IN_HANDLE,
			style: { stroke: edgeStroke({ edge_kind: link.edgeKind }), strokeWidth: 2 },
			data: { edgeKind: link.edgeKind, sourcePort: link.sourcePort, targetPort: link.targetPort, via: link.via, internal: false },
		});
	}
	for (const relay of model.intraNodeRelayLinks) {
		const nodeFrame = framesById.get(relay.nodeFrameId);
		const deviceFrame = framesById.get(relay.deviceFrameId);
		if (!nodeFrame || !deviceFrame || nodeFrame.id === deviceFrame.id) {
			continue;
		}
		edges.push({
			id: `intra_relay|${deviceFrame.id}~${nodeFrame.id}~${relay.devicePort ?? ''}`,
			source: deviceFrame.id,
			target: nodeFrame.id,
			type: 'smoothstep',
			sourceHandle: DEFAULT_OUT_HANDLE,
			targetHandle: DEFAULT_IN_HANDLE,
			style: { stroke: edgeStroke({ edge_kind: relay.edgeKind }), strokeWidth: 2 },
			data: { edgeKind: relay.edgeKind, sourcePort: relay.devicePort, targetPort: relay.nodePort, via: relay.via, internal: false },
		});
	}
	return edges;
}

function buildNestedHierarchyGraph(
	topology: TopologyResponse,
	focusId: string | null | undefined,
	options: BuildFlowOptions,
): { nodes: Node<TwinNodeData>[]; edges: Edge<TwinEdgeData>[] } {
	const { iconByNodeId, selectedNodeId, highlightedNodeIds, detailLevel } = options;
	const hierarchy = topology.hierarchy ?? [];
	const index = hierarchyIndex(hierarchy);
	const rootId = focusId && index.has(focusId) ? focusId : defaultFocusId(hierarchy);
	const root = rootId ? focusGroup(hierarchy, rootId) : null;
	if (!root) {
		return { nodes: [], edges: [] };
	}
	const spec = detailLevelSpec(detailLevel);
	const ctx: NestedContext = {
		hierarchy,
		index,
		nodeById: new Map(topology.nodes.map(n => [n.id, n])),
		flatNodeIds: new Set(topology.nodes.map(n => n.id)),
		memo: new Map(),
		frameMaxDepth: spec.frameMaxDepth,
		renderLeaves: spec.renderLeaves,
		isolateNodeId: options.isolateNodeId ?? null,
		spacing: { groupGap: DEFAULT_BLOCK_GAP, nodeGap: DEFAULT_NODE_GAP },
	};
	const tree = options.isolateNodeId && root.member_ids?.includes(options.isolateNodeId)
		? (() => {
			const node = ctx.nodeById.get(options.isolateNodeId!);
			return node ? layoutLeaf(node, 0) : layoutFrame(root, 0, ctx);
		})()
		: layoutFrame(root, 0, ctx);

	const rfNodes: Node<TwinNodeData>[] = [];
	const rendered: LaidOut[] = [];
	const walk = (laid: LaidOut, origin: { x: number; y: number }, parentFrameId: string | null) => {
		rendered.push(laid);
		const position = { x: origin.x + laid.x, y: origin.y + laid.y };
		const isSelected = selectedNodeId === laid.id;
		const isHighlighted = highlightedNodeIds?.has(laid.id) ?? false;
		const frameId = laid.isLeaf ? parentFrameId : laid.id;
		if (laid.isLeaf) {
			const node = laid.node;
			rfNodes.push({
				id: laid.id,
				type: 'twinNode',
				position,
				selected: isSelected,
				data: {
					label: laid.label,
					nodeType: node?.node_type ?? 'software_function',
					componentClass: node?.component_class ?? null,
					domain: node?.domain ?? 'software',
					sourceFile: node?.source_file,
					accent: laid.accent,
					iconUrl: iconByNodeId?.get(laid.id),
					isGroup: false,
					nested: true,
					compact: true,
					nodeWidth: N_LEAF_W,
					groupKind: node ? undefined : laid.kind,
					collapsedSummary: node ? undefined : laid.collapsedSummary,
					parentFrameId,
					highlighted: isHighlighted || isSelected,
				},
				selectable: true,
				draggable: false,
				zIndex: 100 + laid.depth,
			});
			return;
		}
		rfNodes.push({
			id: laid.id,
			type: 'twinGroup',
			position,
			selected: isSelected,
			data: {
				label: laid.label,
				nodeType: 'group',
				accent: laid.accent,
				iconUrl: iconByNodeId?.get(laid.id),
				isGroup: true,
				nested: true,
				frameDepth: laid.depth,
				groupKind: laid.kind,
				deploymentRole: laid.kind,
				packageId: laid.packageId,
				collapsedSummary: laid.collapsedSummary,
				minimalFrame: laid.minimal,
				parentFrameId,
				highlighted: isHighlighted || isSelected,
			},
			style: { width: laid.width, height: laid.height },
			selectable: true,
			draggable: laid.kind === 'qkd_node' || laid.kind === 'qkd_device' || laid.kind === 'qkd_system',
			zIndex: laid.depth,
		});
		for (const child of laid.children) {
			walk(child, position, frameId);
		}
	};
	walk(tree, { x: 48, y: 32 }, null);

	const model = buildTopologyModel(topology);
	const bestByFlat = new Map<string, LaidOut>();
	const nodeFrameBySide = new Map<string, LaidOut>();
	for (const r of rendered) {
		for (const fid of r.flatMembers) {
			const cur = bestByFlat.get(fid);
			if (!cur || r.depth > cur.depth) {
				bestByFlat.set(fid, r);
			}
		}
		if (r.kind === 'qkd_node') {
			const side = model.groupsById.get(r.id)?.endpoint_side;
			if (side && !nodeFrameBySide.has(side)) {
				nodeFrameBySide.set(side, r);
			}
		}
	}
	const framesById = new Map<string, LaidOut>();
	for (const r of rendered) {
		if (!r.isLeaf) {
			framesById.set(r.id, r);
		}
	}
	return {
		nodes: rfNodes,
		edges: buildNestedEdges(topology, bestByFlat, nodeFrameBySide, framesById, model),
	};
}
