import type { HierarchyGroup, TopologyResponse } from '../../../src/apiTypes';

export const HIERARCHY_KIND_LABELS: Record<string, string> = {
	qkd_system: 'QKD system',
	qkd_node: 'QKD node',
	qkd_device: 'QKD device',
	kms: 'Key management',
	kms_component: 'KMS component',
	post_processing: 'Post-processing',
	network_coordination: 'Network coordination',
	domain: 'Domain',
	software_group: 'Software group',
	module: 'Module',
};

export const HIERARCHY_KIND_COLORS: Record<string, string> = {
	qkd_system: '#6366f1',
	qkd_node: '#8b5cf6',
	qkd_device: '#0ea5e9',
	kms: '#10b981',
	kms_component: '#14b8a6',
	post_processing: '#f43f5e',
	network_coordination: '#0891b2',
	domain: '#64748b',
	software_group: '#7c3aed',
	module: '#f59e0b',
};

export function isPackageTopology(topology: TopologyResponse): boolean {
	const version = topology.schema_version ?? '';
	return version.startsWith('3.1') || Boolean(topology.hierarchy?.some(g => g.group_kind === 'kms'));
}

export function preferredTopologyView(topology: TopologyResponse): 'hierarchy' | 'full' {
	return isPackageTopology(topology) && (topology.hierarchy?.length ?? 0) > 0 ? 'hierarchy' : 'full';
}

export function hierarchyGroupAccent(group: HierarchyGroup): string {
	return HIERARCHY_KIND_COLORS[group.group_kind] ?? '#64748b';
}

export function hierarchyKindLabel(kind: string): string {
	return HIERARCHY_KIND_LABELS[kind] ?? kind.replace(/_/g, ' ');
}

export type DetailLevel = 'nodes' | 'subsystems' | 'modules' | 'components';

export type DetailLevelSpec = {
	id: DetailLevel;
	label: string;
	hint: string;
	frameMaxDepth: number;
	renderLeaves: boolean;
};

export const DETAIL_LEVELS: DetailLevelSpec[] = [
	{ id: 'nodes', label: 'Nodes', hint: 'System → QKD nodes only', frameMaxDepth: 1, renderLeaves: false },
	{ id: 'subsystems', label: 'Subsystems', hint: 'Nodes → devices, KMS, software groups', frameMaxDepth: 2, renderLeaves: false },
	{ id: 'modules', label: 'Full hierarchy', hint: 'All structural frames', frameMaxDepth: Number.POSITIVE_INFINITY, renderLeaves: false },
	{ id: 'components', label: 'Components', hint: 'Expand components inside every module', frameMaxDepth: Number.POSITIVE_INFINITY, renderLeaves: true },
];

export const DEFAULT_DETAIL_LEVEL: DetailLevel = 'modules';

export function detailLevelSpec(level: DetailLevel | undefined): DetailLevelSpec {
	return DETAIL_LEVELS.find(l => l.id === level) ?? DETAIL_LEVELS[2];
}
