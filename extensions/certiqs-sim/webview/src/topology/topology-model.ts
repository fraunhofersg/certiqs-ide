import type { HierarchyGroup, TopologyPort, TopologyResponse } from '../../../src/apiTypes';

export type LayoutLane = 'left' | 'right' | 'center' | 'top' | 'bottom' | string;

export type NodeLayoutHint = {
	lane: LayoutLane | null;
	order: number;
	endpointSide: string | null;
	nodeRole: string | null;
	authoritativeHost: boolean;
};

export type InterNodeLink = {
	sourceNodeId: string;
	targetNodeId: string;
	sourceFrameId: string;
	targetFrameId: string;
	sourceEndpointSide: string | null;
	targetEndpointSide: string | null;
	sourcePort: string | null;
	targetPort: string | null;
	edgeKind: string;
	via: string | null;
	sourceFile: string | null;
};

export type IntraNodeRelayLink = {
	nodeId: string;
	nodeFrameId: string;
	deviceFrameId: string;
	nodePort: string | null;
	devicePort: string | null;
	edgeKind: string;
	via: string | null;
	sourceFile: string | null;
};

export type TopologyModel = {
	systemId: string | null;
	groupsById: Map<string, HierarchyGroup>;
	qkdNodes: HierarchyGroup[];
	nodesByLane: Map<string, HierarchyGroup[]>;
	nodesByEndpointSide: Map<string, HierarchyGroup>;
	authoritativeHostNode: HierarchyGroup | null;
	interNodeLinks: InterNodeLink[];
	intraNodeRelayLinks: IntraNodeRelayLink[];
};

const INTER_NODE_EDGE_KINDS = new Set(['classical', 'digital', 'link']);

function allPorts(group: HierarchyGroup): TopologyPort[] {
	const ports = group.ports;
	if (!ports) {
		return [];
	}
	return [...(ports.inputs ?? []), ...(ports.outputs ?? []), ...(ports.bidirectional ?? [])];
}

function isInterNodeLinkPort(port: TopologyPort): boolean {
	const medium = port.edge_kind ?? port.medium;
	return Boolean(medium && INTER_NODE_EDGE_KINDS.has(medium));
}

export function layoutHintForGroup(group: HierarchyGroup): NodeLayoutHint {
	return {
		lane: (group.lane as LayoutLane | undefined) ?? null,
		order: typeof group.order === 'number' ? group.order : 0,
		endpointSide: group.endpoint_side ?? null,
		nodeRole: group.node_role ?? null,
		authoritativeHost: Boolean(group.authoritative_host),
	};
}

export function buildTopologyModel(topology: TopologyResponse): TopologyModel {
	const hierarchy = topology.hierarchy ?? [];
	const groupsById = new Map(hierarchy.map(g => [g.id, g]));
	const qkdNodes = hierarchy.filter(g => g.group_kind === 'qkd_node');
	const nodesByLane = new Map<string, HierarchyGroup[]>();
	const nodesByEndpointSide = new Map<string, HierarchyGroup>();

	for (const node of qkdNodes) {
		const hint = layoutHintForGroup(node);
		if (hint.lane) {
			const bucket = nodesByLane.get(hint.lane) ?? [];
			bucket.push(node);
			nodesByLane.set(hint.lane, bucket);
		}
		if (hint.endpointSide) {
			nodesByEndpointSide.set(hint.endpointSide, node);
		}
	}

	for (const [, nodes] of nodesByLane) {
		nodes.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
	}

	const authoritativeHostNode =
		qkdNodes.find(g => g.authoritative_host)
		?? qkdNodes.find(g => layoutHintForGroup(g).authoritativeHost)
		?? null;

	return {
		systemId: hierarchy.find(g => g.group_kind === 'qkd_system')?.id ?? null,
		groupsById,
		qkdNodes,
		nodesByLane,
		nodesByEndpointSide,
		authoritativeHostNode,
		interNodeLinks: resolveInterNodeLinks(topology, qkdNodes),
		intraNodeRelayLinks: resolveIntraNodeRelayLinks(topology, qkdNodes),
	};
}

function relayMatches(devicePort: TopologyPort, nodePort: TopologyPort): boolean {
	if (devicePort.signal_type && nodePort.signal_type && devicePort.signal_type === nodePort.signal_type) {
		return true;
	}
	const d = devicePort.id;
	const n = nodePort.id;
	return n !== d && (n.startsWith(d) || d.startsWith(n) || n.includes(d));
}

function resolveIntraNodeRelayLinks(
	topology: TopologyResponse,
	qkdNodes: HierarchyGroup[],
): IntraNodeRelayLink[] {
	const hierarchy = topology.hierarchy ?? [];
	const links: IntraNodeRelayLink[] = [];
	const usedDevicePorts = new Set<string>();

	for (const node of qkdNodes) {
		const nodePorts = allPorts(node).filter(isInterNodeLinkPort);
		if (!nodePorts.length) {
			continue;
		}
		const devices = hierarchy.filter(g => g.group_kind === 'qkd_device' && g.parent_id === node.id);
		for (const nodePort of nodePorts) {
			for (const device of devices) {
				const devicePort = allPorts(device)
					.filter(isInterNodeLinkPort)
					.find(p => !usedDevicePorts.has(`${device.id}:${p.id}`) && relayMatches(p, nodePort));
				if (!devicePort) {
					continue;
				}
				usedDevicePorts.add(`${device.id}:${devicePort.id}`);
				links.push({
					nodeId: node.id,
					nodeFrameId: node.id,
					deviceFrameId: device.id,
					nodePort: nodePort.id,
					devicePort: devicePort.id,
					edgeKind: nodePort.edge_kind ?? devicePort.edge_kind ?? 'digital',
					via: null,
					sourceFile: nodePort.source_file ?? devicePort.source_file ?? null,
				});
				break;
			}
		}
	}
	return links;
}

function resolveInterNodeLinks(
	topology: TopologyResponse,
	qkdNodes: HierarchyGroup[],
): InterNodeLink[] {
	const measurementNodes = qkdNodes.filter(g => g.node_role === 'measurement_node');
	if (measurementNodes.length < 2) {
		return [];
	}
	const links: InterNodeLink[] = [];
	const seen = new Set<string>();
	for (let i = 0; i < measurementNodes.length; i++) {
		for (let j = i + 1; j < measurementNodes.length; j++) {
			const a = measurementNodes[i];
			const b = measurementNodes[j];
			const binding = resolvePairBinding(topology, a, b);
			if (!binding) {
				continue;
			}
			const key = [a.id, b.id].sort().join('~');
			if (seen.has(key)) {
				continue;
			}
			seen.add(key);
			links.push({
				sourceNodeId: a.id,
				targetNodeId: b.id,
				sourceFrameId: binding.sourceFrameId,
				targetFrameId: binding.targetFrameId,
				sourceEndpointSide: a.endpoint_side ?? null,
				targetEndpointSide: b.endpoint_side ?? null,
				sourcePort: binding.sourcePort,
				targetPort: binding.targetPort,
				edgeKind: binding.edgeKind,
				via: binding.via,
				sourceFile: binding.sourceFile,
			});
		}
	}
	return links;
}

function nodeFrameCandidates(topology: TopologyResponse, node: HierarchyGroup): HierarchyGroup[] {
	const devices = (topology.hierarchy ?? []).filter(g => g.group_kind === 'qkd_device' && g.parent_id === node.id);
	return [node, ...devices];
}

function pickLinkPort(
	candidates: HierarchyGroup[],
	prefer: (direction: string | null | undefined) => boolean,
): { frameId: string; port: TopologyPort } | null {
	for (const group of candidates) {
		const port = allPorts(group).filter(isInterNodeLinkPort).find(p => prefer(p.direction));
		if (port) {
			return { frameId: group.id, port };
		}
	}
	for (const group of candidates) {
		const ports = allPorts(group).filter(isInterNodeLinkPort);
		if (ports.length) {
			return { frameId: group.id, port: ports[0] };
		}
	}
	return null;
}

function resolvePairBinding(
	topology: TopologyResponse,
	sourceNode: HierarchyGroup,
	targetNode: HierarchyGroup,
): {
	sourceFrameId: string;
	targetFrameId: string;
	sourcePort: string | null;
	targetPort: string | null;
	edgeKind: string;
	via: string | null;
	sourceFile: string | null;
} | null {
	const source = pickLinkPort(nodeFrameCandidates(topology, sourceNode), d => d === 'out' || d === 'inout');
	const target = pickLinkPort(nodeFrameCandidates(topology, targetNode), d => d === 'in' || d === 'inout');
	if (!source && !target) {
		return null;
	}
	const sourcePort = source?.port ?? null;
	const targetPort = target?.port ?? null;
	const bindingEdge = topology.edges.find(e =>
		INTER_NODE_EDGE_KINDS.has(e.edge_kind)
		&& (
			(e.source_port === sourcePort?.id && e.target_port === targetPort?.id)
			|| (e.source_port === targetPort?.id && e.target_port === sourcePort?.id)
		),
	);
	const channelNode = topology.nodes.find(n =>
		n.node_type === 'channel'
		&& (n.component_class === 'classical_network_link' || n.edge_kind === 'digital'),
	);
	return {
		sourceFrameId: source?.frameId ?? sourceNode.id,
		targetFrameId: target?.frameId ?? targetNode.id,
		sourcePort: sourcePort?.id ?? bindingEdge?.source_port ?? null,
		targetPort: targetPort?.id ?? bindingEdge?.target_port ?? null,
		edgeKind: bindingEdge?.edge_kind ?? sourcePort?.edge_kind ?? 'digital',
		via: bindingEdge?.via ?? channelNode?.label ?? null,
		sourceFile: bindingEdge?.source_file ?? channelNode?.source_file ?? 'network/channels.yaml',
	};
}

export function stagingLaneForGroup(group: HierarchyGroup): LayoutLane | 'other' {
	const hint = layoutHintForGroup(group);
	if (hint.lane) {
		return hint.lane;
	}
	if (hint.nodeRole === 'entangled_source') {
		return 'center';
	}
	return 'other';
}

export function coordinationHostEndpointSide(model: TopologyModel): string | null {
	return model.authoritativeHostNode?.endpoint_side ?? null;
}
