import type {
	ComponentClassification,
	ComponentInventoryEntry,
	TopologyResponse,
} from '../../../src/apiTypes';

export function topologyConnectedIds(topology: TopologyResponse): Set<string> {
	if (topology.connected_node_ids?.length) {
		return new Set(topology.connected_node_ids);
	}
	const ids = new Set<string>();
	for (const edge of topology.edges) {
		ids.add(edge.source);
		ids.add(edge.target);
	}
	return ids;
}

export function inventoryEntryConnected(
	entry: ComponentInventoryEntry,
	topology: TopologyResponse | undefined,
): boolean {
	if (!topology) {
		return true;
	}
	return topology.nodes.some(n => n.id === entry.logical_component_id)
		&& topologyConnectedIds(topology).has(entry.logical_component_id);
}

export function taxonomyIconUrl(iconBase: string | undefined, classification: ComponentClassification | null | undefined): string | undefined {
	if (!iconBase) {
		return undefined;
	}
	const id = classification?.subcategory_id ?? classification?.category_id ?? 'quantum_sources';
	return `${iconBase.replace(/\/$/, '')}/${id}.svg`;
}

export function componentTitle(entry: ComponentInventoryEntry): string {
	return entry.logical_component_id.replace(/_/g, ' ');
}
