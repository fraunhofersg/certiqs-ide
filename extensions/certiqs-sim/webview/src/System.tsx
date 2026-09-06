import { Button, Card, Chip, Input, Label, Spinner, Tabs, TextField } from '@heroui/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type {
	ComponentInventoryEntry,
	ComponentInventoryResponse,
	ConfigEntry,
	ConfigFilesResponse,
	MetaResponse,
	ParamMeta,
	TaxonomyResponse,
	TopologyResponse,
} from '../../src/apiTypes';
import type { SimState } from '../../src/protocol';
import { rpc } from './hostRpc';
import { ComponentsView } from './topology/ComponentsView';
import { canDrillInto } from './topology/hierarchy-layout';
import { hierarchyKindLabel } from './topology/hierarchy-ui';
import { taxonomyIconUrl, topologyConnectedIds } from './topology/inventory';
import { TopologyCanvas } from './topology/TopologyCanvas';
import { useHierarchyDrill } from './topology/useHierarchyDrill';
import { TopologyHierarchyBreadcrumb, TopologyLegend, TopologyViewModes } from './topology/ViewModes';
import { onHostMessage, post } from './vscodeApi';

type TabKey = 'configuration' | 'system-design' | 'components';

export function System(): JSX.Element {
	const [state, setState] = useState<SimState | undefined>();
	const [tab, setTab] = useState<TabKey>('system-design');
	const [configs, setConfigs] = useState<ConfigEntry[]>([]);
	const [files, setFiles] = useState<ConfigFilesResponse | undefined>();
	const [meta, setMeta] = useState<MetaResponse | null>(null);
	const [inventory, setInventory] = useState<ComponentInventoryResponse | undefined>();
	const [taxonomy, setTaxonomy] = useState<TaxonomyResponse | undefined>();
	const [topology, setTopology] = useState<TopologyResponse | undefined>();
	const [selected, setSelected] = useState<string | null>(null);
	const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
	const [overrides, setOverrides] = useState<Record<string, number>>({});
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | undefined>();

	const configName = state?.configName ?? files?.config ?? 'bbm92-minimal';

	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'state') {
				setState(message.payload);
			}
		});
		post({ type: 'ready' });
		return dispose;
	}, []);

	useEffect(() => {
		if (!state) {
			return;
		}
		let cancelled = false;
		setLoading(true);
		Promise.all([
			rpc<import('../../src/apiTypes').ConfigsResponse>('getConfigs'),
			rpc<MetaResponse>('getMeta'),
			rpc<ConfigFilesResponse>('getConfigFiles', { config: state.configName }),
			rpc<ComponentInventoryResponse>('getComponentInventory', { config: state.configName }),
			rpc<TaxonomyResponse>('getComponentTaxonomy', { config: state.configName }).catch(() => undefined),
			rpc<TopologyResponse>('getComponentTopology', { config: state.configName }),
		]).then(([listed, nextMeta, nextFiles, nextInventory, nextTaxonomy, nextTopology]) => {
			if (cancelled) {
				return;
			}
			setConfigs(listed.configs ?? []);
			setMeta(nextMeta);
			setFiles(nextFiles);
			setInventory(nextInventory);
			setTaxonomy(nextTaxonomy);
			setTopology(nextTopology);
			setError(undefined);
		}).catch(err => {
			if (!cancelled) {
				setError((err as Error).message);
			}
		}).finally(() => {
			if (!cancelled) {
				setLoading(false);
			}
		});
		return () => {
			cancelled = true;
		};
	}, [state?.configName]);

	const onSelectNode = useCallback((id: string | null) => {
		setSelected(id);
		setSelectedEdge(null);
	}, []);
	const onSelectEdge = useCallback((id: string | null) => {
		setSelectedEdge(id);
		if (id) {
			setSelected(null);
		}
	}, []);

	const drill = useHierarchyDrill({
		topology,
		onSelectNode,
		onSelectEdge,
	});

	const iconByNodeId = useMemo(() => {
		const map = new Map<string, string>();
		const iconBase = state?.iconBase;
		for (const node of topology?.nodes ?? []) {
			const inv = inventory?.components.find(c => c.logical_component_id === node.id);
			const url = taxonomyIconUrl(iconBase, inv?.classification);
			if (url) {
				map.set(node.id, url);
			}
		}
		for (const group of topology?.hierarchy ?? []) {
			const inv = inventory?.components.find(c =>
				c.structural_path?.package_id === group.package_id
				&& (c.structural_path?.module_id === group.id || c.structural_path?.node_id === group.id),
			);
			const url = taxonomyIconUrl(iconBase, inv?.classification);
			if (url) {
				map.set(group.id, url);
			}
		}
		return map;
	}, [inventory, state?.iconBase, topology]);

	const selectedInventory = useMemo(
		(): ComponentInventoryEntry | null =>
			inventory?.components.find(c => c.logical_component_id === selected) ?? null,
		[inventory, selected],
	);
	const selectedHierarchy = drill.selectedHierarchyGroup(selected);
	const selectedGraphNode = topology?.nodes.find(n => n.id === selected) ?? null;
	const selectedGraphGroup = topology?.groups?.find(g => g.id === selected) ?? null;
	const selectedGraphEdge = topology?.edges.find(e => e.id === selectedEdge) ?? null;
	const defaults = configs.find(item => item.name === configName)?.defaults ?? {};

	return (
		<div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-5">
			<header className="flex flex-wrap items-center justify-between gap-3">
				<div>
					<p className="text-xs font-semibold tracking-wide text-accent">System</p>
					<h1 className="text-xl font-semibold">Configuration and topology</h1>
					<p className="text-xs text-muted">Bundled YAML under the control-plane config root. Simulated only.</p>
				</div>
				<Chip size="sm" variant="soft">{configName}</Chip>
			</header>

			{error ? <Card className="p-3 text-sm text-danger">System API unavailable — {error}</Card> : null}

			<Tabs selectedKey={tab} onSelectionChange={key => setTab(String(key) as TabKey)} variant="secondary">
				<Tabs.ListContainer>
					<Tabs.List aria-label="System views" className="w-fit">
						<Tabs.Tab id="configuration">Configuration<Tabs.Indicator /></Tabs.Tab>
						<Tabs.Tab id="system-design"><Tabs.Separator />System Design<Tabs.Indicator /></Tabs.Tab>
						<Tabs.Tab id="components"><Tabs.Separator />Components<Tabs.Indicator /></Tabs.Tab>
					</Tabs.List>
				</Tabs.ListContainer>

				<Tabs.Panel id="configuration" className="pt-4">
					{loading ? <Spinner /> : (
						<div className="flex flex-col gap-4">
							<div className="flex flex-col gap-1.5">
								<Label htmlFor="system-config">Configuration set</Label>
								<select
									id="system-config"
									className="max-w-md rounded-md border border-separator bg-surface px-3 py-2 font-mono text-sm"
									value={configName}
									onChange={event => post({ type: 'setConfig', configName: event.target.value })}
								>
									{(configs.length ? configs.map(item => item.name) : [configName]).map(name => (
										<option key={name} value={name}>{name}</option>
									))}
								</select>
							</div>
							<Card className="p-4">
								<Card.Title>{files?.manifest_name ?? configName}</Card.Title>
								<Card.Description>{files?.manifest_description ?? files?.config_dir}</Card.Description>
								<ul className="mt-3 space-y-1 font-mono text-xs text-muted">
									{(files?.files ?? []).map(file => (
										<li key={file.name}>{file.present ? '●' : '○'} {file.name}{file.imported ? ' (imported)' : ''}</li>
									))}
								</ul>
							</Card>
							<div className="grid grid-cols-1 gap-3 md:grid-cols-2">
								{(meta?.base_params ?? []).slice(0, 12).map(param => (
									<ParamField
										key={param.key}
										param={param}
										value={overrides[param.key] ?? defaults[param.key] ?? param.min}
										onChange={value => setOverrides(current => ({ ...current, [param.key]: value }))}
									/>
								))}
							</div>
							<Button
								size="sm"
								isDisabled={!state?.status?.run_id || state.status.status === 'idle'}
								onPress={() => {
									if (state?.status?.run_id) {
										void rpc('setParams', { runId: state.status.run_id, overrides });
									}
								}}
							>
								Apply to running twin
							</Button>
						</div>
					)}
				</Tabs.Panel>

				<Tabs.Panel id="system-design" className="pt-4">
					{loading || !topology ? <Spinner /> : (
						<div className="flex flex-col gap-3">
							<div className="flex flex-wrap items-center gap-2">
								<Chip size="sm" variant="soft">{topology.system.protocol ?? 'BBM92'}</Chip>
								{topology.system.topology ? <Chip size="sm" variant="soft">{topology.system.topology.replace(/_/g, ' ')}</Chip> : null}
								{topology.schema_version ? <Chip size="sm" variant="soft">schema {topology.schema_version}</Chip> : null}
								<Chip size="sm" variant="soft">{topologyConnectedIds(topology).size} connected</Chip>
								<Chip size="sm" variant="soft">{topology.edge_count} links</Chip>
								<Chip size="sm" variant="soft">{topology.hierarchy?.length ?? 0} hierarchy frames</Chip>
							</div>

							<TopologyViewModes
								topology={topology}
								viewMode={drill.viewMode}
								onViewModeChange={drill.setViewMode}
								detailLevel={drill.detailLevel}
								onDetailLevelChange={drill.setDetailLevel}
							/>

							{drill.viewMode === 'hierarchy' && drill.hasHierarchy ? (
								<TopologyHierarchyBreadcrumb
									breadcrumb={drill.breadcrumb}
									focusId={drill.hierarchyFocusId}
									canDrillSelected={Boolean(selectedHierarchy && canDrillInto(selectedHierarchy))}
									selectedLabel={selectedHierarchy?.label}
									onNavigate={drill.navigateBreadcrumb}
									onDrill={() => drill.drillIntoSelection(selectedHierarchy)}
								/>
							) : null}

							<TopologyLegend />

							<div className="grid gap-4 xl:grid-cols-[1fr_280px]">
								<TopologyCanvas
									topology={topology}
									mode={drill.viewMode}
									hierarchyFocusId={drill.hierarchyFocusId}
									detailLevel={drill.detailLevel}
									isolateNodeId={drill.isolateNodeId}
									iconByNodeId={iconByNodeId}
									selectedNodeId={selected}
									selectedEdgeId={selectedEdge}
									highlightedNodeIds={selected ? new Set([selected]) : undefined}
									onSelectNode={drill.viewMode === 'hierarchy' ? drill.handleHierarchyNodeSelect : onSelectNode}
									onSelectEdge={onSelectEdge}
									onDrillInto={drill.viewMode === 'hierarchy' ? drill.handleDrillIntoNode : undefined}
									flowNavigation={
										drill.viewMode === 'hierarchy' && drill.hasHierarchy
											? {
												breadcrumb: drill.breadcrumb,
												focusId: drill.hierarchyFocusId,
												canGoUp: drill.breadcrumb.length > 1,
												onNavigate: drill.navigateBreadcrumb,
												onGoUp: drill.drillUp,
											}
											: undefined
									}
									heightClass="h-[min(72vh,760px)]"
								/>
								<Card className="h-fit p-4">
									{selectedGraphEdge ? (
										<>
											<p className="text-sm font-semibold">Connection</p>
											<p className="text-xs text-muted">{selectedGraphEdge.edge_kind}</p>
											<p className="mt-2 font-mono text-[11px]">{selectedGraphEdge.source} → {selectedGraphEdge.target}</p>
										</>
									) : selectedHierarchy ? (
										<>
											<p className="text-sm font-semibold capitalize">{selectedHierarchy.label}</p>
											<p className="text-xs text-muted">{hierarchyKindLabel(selectedHierarchy.group_kind)}</p>
											<p className="mt-2 text-xs text-muted">{selectedHierarchy.member_ids?.length ?? 0} members · {selectedHierarchy.children?.length ?? 0} children</p>
										</>
									) : selectedInventory ? (
										<>
											<p className="text-sm font-semibold capitalize">{selectedInventory.logical_component_id.replace(/_/g, ' ')}</p>
											<p className="text-xs text-muted">{selectedInventory.component_class}</p>
										</>
									) : selectedGraphGroup ? (
										<>
											<p className="text-sm font-semibold">{selectedGraphGroup.label}</p>
											<p className="text-xs text-muted">{selectedGraphGroup.group_kind}</p>
										</>
									) : selectedGraphNode ? (
										<>
											<p className="text-sm font-semibold">{selectedGraphNode.label}</p>
											<p className="text-xs text-muted">{selectedGraphNode.node_type} · {selectedGraphNode.component_class ?? '—'}</p>
										</>
									) : (
										<p className="text-sm text-muted">Select a frame or component. Double-click a hierarchy frame to drill in.</p>
									)}
								</Card>
							</div>
						</div>
					)}
				</Tabs.Panel>

				<Tabs.Panel id="components" className="pt-4">
					{loading ? <Spinner /> : (
						<ComponentsView
							inventory={inventory}
							taxonomy={taxonomy}
							topology={topology}
							iconBase={state?.iconBase}
							selectedId={selected}
							onSelect={id => {
								setSelected(id);
								setSelectedEdge(null);
							}}
						/>
					)}
				</Tabs.Panel>
			</Tabs>
		</div>
	);
}

function ParamField(props: { param: ParamMeta; value: number; onChange: (value: number) => void }): JSX.Element {
	return (
		<TextField name={props.param.key} type="number" value={String(props.value)} onChange={value => props.onChange(Number(value))}>
			<Label>{props.param.label}</Label>
			<Input min={props.param.min} max={props.param.max} step={props.param.step} className="tabular-nums" />
		</TextField>
	);
}
