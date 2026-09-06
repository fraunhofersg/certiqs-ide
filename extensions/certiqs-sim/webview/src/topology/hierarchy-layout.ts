import type { HierarchyGroup, TopologyNode } from '../../../src/apiTypes';
import { stagingLaneForGroup } from './topology-model';

export function hierarchyIndex(groups: HierarchyGroup[] | undefined): Map<string, HierarchyGroup> {
	return new Map((groups ?? []).map(g => [g.id, g]));
}

export function systemGroup(groups: HierarchyGroup[] | undefined): HierarchyGroup | null {
	return groups?.find(g => g.group_kind === 'qkd_system') ?? null;
}

export function defaultFocusId(groups: HierarchyGroup[] | undefined): string | null {
	return systemGroup(groups)?.id ?? groups?.[0]?.id ?? null;
}

export function focusGroup(
	groups: HierarchyGroup[] | undefined,
	focusId: string | null,
): HierarchyGroup | null {
	if (!focusId || !groups) {
		return null;
	}
	return groups.find(g => g.id === focusId) ?? null;
}

export function focusBreadcrumb(
	groups: HierarchyGroup[] | undefined,
	focusId: string | null,
): HierarchyGroup[] {
	const index = hierarchyIndex(groups);
	const trail: HierarchyGroup[] = [];
	let current = focusId ? index.get(focusId) : undefined;
	while (current) {
		trail.unshift(current);
		current = current.parent_id ? index.get(current.parent_id) : undefined;
	}
	return trail;
}

export function childGroups(
	groups: HierarchyGroup[] | undefined,
	focusId: string | null,
): HierarchyGroup[] {
	const focus = focusGroup(groups, focusId);
	if (!focus?.children?.length) {
		return [];
	}
	const index = hierarchyIndex(groups);
	return focus.children
		.map(id => index.get(id))
		.filter((g): g is HierarchyGroup => Boolean(g));
}

export function canDrillInto(group: HierarchyGroup | null): boolean {
	if (!group) {
		return false;
	}
	if (group.children?.length) {
		return true;
	}
	if (group.group_kind === 'module' && Boolean(group.member_ids?.length)) {
		return true;
	}
	if (
		(group.group_kind === 'component' || group.group_kind === 'kms_component')
		&& Boolean(group.member_ids?.length)
	) {
		return true;
	}
	return false;
}

export function findHierarchyGroupForNodeId(
	groups: HierarchyGroup[] | undefined,
	nodeId: string,
): HierarchyGroup | null {
	if (!groups?.length) {
		return null;
	}
	const direct = groups.find(g => g.id === nodeId);
	if (direct) {
		return direct;
	}
	const candidates = groups.filter(g => g.member_ids?.includes(nodeId));
	if (candidates.length === 0) {
		return null;
	}
	const rank = (g: HierarchyGroup) => {
		if (g.group_kind === 'component' || g.group_kind === 'kms_component') {
			return 0;
		}
		if (g.group_kind === 'module') {
			return 1;
		}
		return 2;
	};
	return [...candidates].sort((a, b) => rank(a) - rank(b))[0];
}

export function stagingLane(group: HierarchyGroup): string {
	return String(stagingLaneForGroup(group));
}

export function memberNodesForFocus(
	nodes: TopologyNode[],
	groups: HierarchyGroup[] | undefined,
	focusId: string | null,
): TopologyNode[] {
	const focus = focusGroup(groups, focusId);
	if (!focus?.member_ids?.length) {
		return [];
	}
	const memberSet = new Set(focus.member_ids);
	return nodes.filter(n => memberSet.has(n.id) && n.node_type !== 'subsystem');
}
