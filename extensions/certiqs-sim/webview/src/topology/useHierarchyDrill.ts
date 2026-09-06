import { useCallback, useEffect, useMemo, useState } from 'react';
import type { HierarchyGroup, TopologyResponse } from '../../../src/apiTypes';
import {
	canDrillInto,
	defaultFocusId,
	findHierarchyGroupForNodeId,
	focusBreadcrumb,
	focusGroup,
	hierarchyIndex,
} from './hierarchy-layout';
import { DEFAULT_DETAIL_LEVEL, preferredTopologyView, type DetailLevel } from './hierarchy-ui';
import type { ViewMode } from './layout';

export function useHierarchyDrill(options: {
	topology: TopologyResponse | undefined;
	onSelectNode?: (id: string | null) => void;
	onSelectEdge?: (id: string | null) => void;
}) {
	const { topology, onSelectNode, onSelectEdge } = options;
	const hasHierarchy = Boolean(topology?.hierarchy?.length);
	const [viewMode, setViewMode] = useState<ViewMode>('full');
	const [hierarchyFocusId, setHierarchyFocusId] = useState<string | null>(null);
	const [detailLevel, setDetailLevel] = useState<DetailLevel>(DEFAULT_DETAIL_LEVEL);
	const [isolateNodeId, setIsolateNodeId] = useState<string | null>(null);

	useEffect(() => {
		if (!topology) {
			return;
		}
		setHierarchyFocusId(defaultFocusId(topology.hierarchy));
		setViewMode(preferredTopologyView(topology));
		setDetailLevel(DEFAULT_DETAIL_LEVEL);
		setIsolateNodeId(null);
	}, [topology?.manifest_sha256, topology?.schema_version, topology]);

	const hierarchyMap = useMemo(() => hierarchyIndex(topology?.hierarchy), [topology?.hierarchy]);
	const breadcrumb = useMemo(
		() => focusBreadcrumb(topology?.hierarchy, hierarchyFocusId),
		[topology?.hierarchy, hierarchyFocusId],
	);
	const focusedGroup = useMemo(
		() => focusGroup(topology?.hierarchy, hierarchyFocusId),
		[topology?.hierarchy, hierarchyFocusId],
	);

	const navigateBreadcrumb = useCallback((groupId: string) => {
		setHierarchyFocusId(groupId);
		setIsolateNodeId(null);
		onSelectNode?.(groupId);
		onSelectEdge?.(null);
	}, [onSelectEdge, onSelectNode]);

	const drillUp = useCallback(() => {
		const current = focusGroup(topology?.hierarchy, hierarchyFocusId);
		if (!current?.parent_id) {
			return;
		}
		setHierarchyFocusId(current.parent_id);
		setIsolateNodeId(null);
		onSelectNode?.(current.parent_id);
		onSelectEdge?.(null);
	}, [hierarchyFocusId, onSelectEdge, onSelectNode, topology?.hierarchy]);

	const handleHierarchyNodeSelect = useCallback((nodeId: string | null) => {
		onSelectNode?.(nodeId);
		onSelectEdge?.(null);
	}, [onSelectEdge, onSelectNode]);

	const drillIntoSelection = useCallback((group: HierarchyGroup | null) => {
		if (!group || !canDrillInto(group)) {
			return;
		}
		setHierarchyFocusId(group.id);
		setIsolateNodeId(null);
		if (group.group_kind === 'module') {
			setDetailLevel('components');
		}
		onSelectNode?.(group.id);
		onSelectEdge?.(null);
	}, [onSelectEdge, onSelectNode]);

	const handleDrillIntoNode = useCallback((nodeId: string) => {
		const group = hierarchyMap.get(nodeId) ?? findHierarchyGroupForNodeId(topology?.hierarchy, nodeId);
		if (group && canDrillInto(group)) {
			setHierarchyFocusId(group.id);
			setIsolateNodeId(null);
			if (group.group_kind === 'module' || group.group_kind === 'component') {
				setDetailLevel('components');
			}
			onSelectNode?.(group.id);
			onSelectEdge?.(null);
			return;
		}
		const focus = focusGroup(topology?.hierarchy, hierarchyFocusId);
		if (focus?.member_ids?.includes(nodeId)) {
			setDetailLevel('components');
			setIsolateNodeId(nodeId);
			onSelectNode?.(nodeId);
			onSelectEdge?.(null);
		}
	}, [hierarchyFocusId, hierarchyMap, onSelectEdge, onSelectNode, topology?.hierarchy]);

	const selectedHierarchyGroup = useCallback((selectedId: string | null): HierarchyGroup | null => {
		if (!selectedId) {
			return null;
		}
		return hierarchyMap.get(selectedId) ?? null;
	}, [hierarchyMap]);

	return {
		hasHierarchy,
		viewMode,
		setViewMode,
		hierarchyFocusId,
		detailLevel,
		setDetailLevel,
		isolateNodeId,
		breadcrumb,
		focusedGroup,
		navigateBreadcrumb,
		drillUp,
		handleHierarchyNodeSelect,
		drillIntoSelection,
		handleDrillIntoNode,
		selectedHierarchyGroup,
	};
}
