import type { TopologyEdge, TopologyNode } from '../../../src/apiTypes';

export const DEFAULT_IN_HANDLE = '__in';
export const DEFAULT_OUT_HANDLE = '__out';

export const NODE_TYPE_LABELS: Record<string, string> = {
	subsystem: 'Subsystem',
	component: 'Component',
	channel: 'Channel',
	post_processing: 'Post-processing',
};

export const EDGE_KIND_COLORS: Record<string, string> = {
	optical: '#38bdf8',
	quantum: '#a78bfa',
	digital: '#fbbf24',
	classical: '#34d399',
	software: '#fb7185',
	link: '#94a3b8',
};

export const DOMAIN_COLORS: Record<string, string> = {
	subsystem: '#6366f1',
	optical: '#0ea5e9',
	channel: '#8b5cf6',
	digital: '#eab308',
	software: '#f43f5e',
};

export const DEPLOYMENT_ROLE_LABELS: Record<string, string> = {
	qkd_device: 'QKD device',
	qkd_node: 'QKD node',
	kms: 'KMS',
	kms_component: 'KMS component',
	post_processing: 'Post-processing',
	domain: 'Domain',
	module: 'Module',
	qkd_system: 'QKD system',
	network_coordination: 'Coordination',
	quantum_source: 'Quantum source',
};

export const DEPLOYMENT_ROLE_COLORS: Record<string, string> = {
	qkd_device: '#0ea5e9',
	qkd_node: '#8b5cf6',
	kms: '#10b981',
	kms_component: '#14b8a6',
	post_processing: '#f43f5e',
	domain: '#64748b',
	module: '#f59e0b',
	qkd_system: '#6366f1',
	network_coordination: '#eab308',
	quantum_source: '#6366f1',
};

export function deploymentRoleLabel(role?: string | null): string | null {
	if (!role) {
		return null;
	}
	return DEPLOYMENT_ROLE_LABELS[role] ?? role.replace(/_/g, ' ');
}

export function nodeAccent(node: TopologyNode): string {
	if (node.node_type === 'subsystem') {
		return DOMAIN_COLORS.subsystem;
	}
	if (node.node_type === 'channel') {
		return DOMAIN_COLORS.channel;
	}
	if (node.node_type === 'post_processing') {
		return DOMAIN_COLORS.software;
	}
	return DOMAIN_COLORS[node.domain ?? 'optical'] ?? '#64748b';
}

export function edgeStroke(edge: Pick<TopologyEdge, 'edge_kind'>): string {
	return EDGE_KIND_COLORS[edge.edge_kind] ?? EDGE_KIND_COLORS.link;
}
