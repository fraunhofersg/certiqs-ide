import type { TopologyGroup, TopologyNode } from '../../../src/apiTypes';

export type LayoutSpacing = {
	blockGap: number;
	nodeGap: number;
};

export const DEFAULT_BLOCK_GAP = 64;
export const DEFAULT_NODE_GAP = 36;
export const NODE_WIDTH = 188;
export const GROUP_HEADER_H = 52;
export const GROUP_MARGIN = 40;
export const CHILD_CELL_W = NODE_WIDTH + 32;
export const CHILD_CELL_H = 156;

const DEPLOYMENT_ROLE_ORDER: Record<string, number> = {
	quantum_source: 0,
	qkd_device: 1,
	network_coordination: 2,
	qkd_node: 3,
};

function subsystemSortKey(node: TopologyNode): string {
	const roleRank = DEPLOYMENT_ROLE_ORDER[node.deployment_role ?? ''] ?? 9;
	const side = node.endpoint_side ?? '';
	return `${roleRank}:${side}:${node.id}`;
}

function nodesByDeploymentRole(nodes: TopologyNode[], role: string): TopologyNode[] {
	return nodes
		.filter(n => n.deployment_role === role)
		.sort((a, b) => subsystemSortKey(a).localeCompare(subsystemSortKey(b)));
}

export type ViewMode = 'system' | 'full' | 'hierarchy';

export function parentForNode(node: TopologyNode): string | undefined {
	if (node.node_type === 'subsystem') {
		return undefined;
	}
	if (node.subsystem) {
		return node.subsystem;
	}
	return undefined;
}

function gridPosition(index: number, cols: number, nodeGap: number) {
	const col = index % cols;
	const row = Math.floor(index / cols);
	const cellW = NODE_WIDTH + nodeGap;
	const cellH = CHILD_CELL_H + Math.round(nodeGap * 0.5);
	return {
		x: GROUP_MARGIN + col * cellW,
		y: GROUP_HEADER_H + GROUP_MARGIN + row * cellH,
	};
}

export function groupStyleForChildren(
	childCount: number,
	cols = 2,
	nodeGap = DEFAULT_NODE_GAP,
): { width: number; height: number } {
	const cellW = NODE_WIDTH + nodeGap;
	const cellH = CHILD_CELL_H + Math.round(nodeGap * 0.5);
	const rows = Math.max(1, Math.ceil(Math.max(childCount, 1) / cols));
	return {
		width: GROUP_MARGIN * 2 + cols * cellW,
		height: GROUP_HEADER_H + GROUP_MARGIN * 2 + rows * cellH,
	};
}

function sortChildren(nodes: TopologyNode[]): TopologyNode[] {
	return [...nodes].sort((a, b) => a.id.localeCompare(b.id));
}

function colsForGroup(sub: TopologyNode): number {
	if (sub.deployment_role === 'quantum_source') {
		return 1;
	}
	if (sub.deployment_role === 'network_coordination') {
		return 2;
	}
	return 2;
}

function layoutFullColumns(
	nodes: TopologyNode[],
	visible: TopologyNode[],
	childrenByParent: Map<string, TopologyNode[]>,
	positions: Map<string, { x: number; y: number }>,
	groupSizes: Map<string, { width: number; height: number }>,
	spacing: LayoutSpacing,
) {
	const subsystems = nodes.filter(n => n.node_type === 'subsystem');

	for (const sub of subsystems) {
		const kids = childrenByParent.get(sub.id) ?? [];
		const sorted = sortChildren(kids);
		const cols = colsForGroup(sub);
		groupSizes.set(sub.id, groupStyleForChildren(sorted.length, cols, spacing.nodeGap));
		sorted.forEach((child, i) => positions.set(child.id, gridPosition(i, cols, spacing.nodeGap)));
	}

	const source = nodesByDeploymentRole(subsystems, 'quantum_source')[0];
	const stations = nodesByDeploymentRole(subsystems, 'qkd_device');
	const coordination = nodesByDeploymentRole(subsystems, 'network_coordination')[0];
	const qkdNodes = nodesByDeploymentRole(subsystems, 'qkd_node');

	const centralSize = source
		? groupSizes.get(source.id) ?? groupStyleForChildren(2, 1, spacing.nodeGap)
		: groupStyleForChildren(2, 1, spacing.nodeGap);
	const stationSizes = stations.map(
		s => groupSizes.get(s.id) ?? groupStyleForChildren(5, 2, spacing.nodeGap),
	);
	const aliceSize = stationSizes[0] ?? groupStyleForChildren(5, 2, spacing.nodeGap);
	const bobSize = stationSizes[1] ?? groupStyleForChildren(5, 2, spacing.nodeGap);
	const coordSize = coordination
		? groupSizes.get(coordination.id) ?? groupStyleForChildren(2, 2, spacing.nodeGap)
		: groupStyleForChildren(2, 2, spacing.nodeGap);
	const qkdNodeSizes = qkdNodes.map(
		n => groupSizes.get(n.id) ?? groupStyleForChildren(2, 2, spacing.nodeGap),
	);
	const aliceNodeSize = qkdNodeSizes[0] ?? groupStyleForChildren(2, 2, spacing.nodeGap);
	const bobNodeSize = qkdNodeSizes[1] ?? groupStyleForChildren(5, 2, spacing.nodeGap);

	const blockGap = spacing.blockGap;
	const laneGap = Math.round(blockGap * 1.25);
	const x0 = 56;
	const rowY = 64;
	const channelX = x0 + centralSize.width + blockGap;
	const stationX = channelX + NODE_WIDTH + blockGap;
	const bobX = stationX + aliceSize.width + laneGap;
	const coordX = bobX + bobSize.width + blockGap;
	const aliceNodeX = coordX + coordSize.width + blockGap;
	const bobNodeX = aliceNodeX + aliceNodeSize.width + laneGap;
	const armHeight = Math.max(aliceSize.height, bobSize.height);
	const nodeArmHeight = Math.max(aliceNodeSize.height, bobNodeSize.height);
	const centralY = rowY + Math.max(0, (armHeight - centralSize.height) / 2);
	const nodeRowY = rowY + Math.max(0, (armHeight - nodeArmHeight) / 2);

	if (source) {
		positions.set(source.id, { x: x0, y: centralY });
	}
	if (stations[0]) {
		positions.set(stations[0].id, { x: stationX, y: rowY });
	}
	if (stations[1]) {
		positions.set(stations[1].id, { x: bobX, y: rowY });
	}
	if (coordination) {
		positions.set(coordination.id, { x: coordX, y: rowY + 24 });
	}
	if (qkdNodes[0]) {
		positions.set(qkdNodes[0].id, { x: aliceNodeX, y: nodeRowY });
	}
	if (qkdNodes[1]) {
		positions.set(qkdNodes[1].id, { x: bobNodeX, y: nodeRowY });
	}

	const channels = sortChildren(visible.filter(n => n.node_type === 'channel'));
	const quantumChannels = channels.filter(c => c.edge_kind === 'quantum' || c.component_class?.includes('fiber'));
	const otherChannels = channels.filter(c => !quantumChannels.includes(c));
	const aliceChannelY = rowY + GROUP_HEADER_H + 48;
	quantumChannels.forEach((ch, index) => {
		positions.set(ch.id, { x: channelX, y: aliceChannelY + index * 12 });
	});
	const otherBaseY = rowY + armHeight + blockGap;
	otherChannels.forEach((ch, i) => {
		positions.set(ch.id, { x: channelX, y: otherBaseY + i * (CHILD_CELL_H * 0.7 + spacing.nodeGap * 0.25) });
	});
}

export function layoutNodes(
	nodes: TopologyNode[],
	mode: ViewMode,
	groups?: TopologyGroup[],
	spacing: LayoutSpacing = { blockGap: DEFAULT_BLOCK_GAP, nodeGap: DEFAULT_NODE_GAP },
) {
	const visible =
		mode === 'system'
			? nodes.filter(n =>
				n.node_type === 'subsystem'
				|| n.node_type === 'channel'
				|| n.component_class === 'coincidence_matcher'
				|| n.component_class === 'key_store_interface',
			)
			: nodes.filter(n => n.node_type !== 'subsystem');

	const positions = new Map<string, { x: number; y: number }>();
	const groupSizes = new Map<string, { width: number; height: number }>();
	const childrenByParent = new Map<string, TopologyNode[]>();

	for (const node of visible) {
		if (node.node_type === 'subsystem') {
			continue;
		}
		const parent = parentForNode(node);
		if (parent) {
			const list = childrenByParent.get(parent) ?? [];
			list.push(node);
			childrenByParent.set(parent, list);
		}
	}

	if (mode === 'full') {
		layoutFullColumns(nodes, visible, childrenByParent, positions, groupSizes, spacing);
	} else {
		const subsystems = nodes.filter(n => n.node_type === 'subsystem');
		const source = nodesByDeploymentRole(subsystems, 'quantum_source')[0];
		const stations = nodesByDeploymentRole(subsystems, 'qkd_device');
		const coordination = nodesByDeploymentRole(subsystems, 'network_coordination')[0];
		const qkdNodes = nodesByDeploymentRole(subsystems, 'qkd_node');
		const x0 = 56;
		if (source) {
			positions.set(source.id, { x: x0, y: 280 });
		}
		if (stations[0]) {
			positions.set(stations[0].id, { x: 560, y: 64 });
		}
		if (stations[1]) {
			positions.set(stations[1].id, { x: 560, y: 420 });
		}
		if (coordination) {
			positions.set(coordination.id, { x: 920, y: 220 });
		}
		if (qkdNodes[0]) {
			positions.set(qkdNodes[0].id, { x: 1180, y: 120 });
		}
		if (qkdNodes[1]) {
			positions.set(qkdNodes[1].id, { x: 1180, y: 360 });
		}
		visible.filter(n => n.node_type === 'channel').forEach((ch, i) => {
			positions.set(ch.id, { x: 400, y: 200 + i * 120 });
		});
		const matchers = nodes.filter(n => n.component_class === 'coincidence_matcher');
		const keyManagers = nodes.filter(n => n.component_class === 'key_store_interface');
		if (matchers[0]) {
			positions.set(matchers[0].id, { x: 920, y: 300 });
		}
		if (keyManagers[0]) {
			positions.set(keyManagers[0].id, { x: 1360, y: 340 });
		}
	}

	return {
		positions,
		visible,
		groupIds: new Set(nodes.filter(n => n.node_type === 'subsystem').map(n => n.id)),
		groupSizes,
		groups,
	};
}

export function groupStyle(
	groupId: string,
	groupSizes?: Map<string, { width: number; height: number }>,
): { width: number; height: number } {
	return groupSizes?.get(groupId) ?? { width: 360, height: 300 };
}

const ROLE_LABELS: Record<string, string> = {
	qkd_device: 'QKD device',
	qkd_node: 'QKD node',
	network_coordination: 'Coordination',
	quantum_source: 'Quantum source',
};

export function groupLabel(groupId: string, groups?: TopologyGroup[]): string {
	const fromApi = groups?.find(g => g.id === groupId);
	if (fromApi?.label) {
		return fromApi.label;
	}
	const role = fromApi?.deployment_role;
	if (role && ROLE_LABELS[role]) {
		return ROLE_LABELS[role];
	}
	return groupId.replace(/_/g, ' ');
}

export function groupMeta(groupId: string, groups?: TopologyGroup[]): TopologyGroup | undefined {
	return groups?.find(g => g.id === groupId);
}
