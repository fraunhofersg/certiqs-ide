import { Card, Chip } from '@heroui/react';
import { useMemo, useState, type ReactNode } from 'react';
import type {
	ComponentInventoryEntry,
	ComponentInventoryResponse,
	TaxonomyResponse,
	TopologyResponse,
} from '../../../src/apiTypes';
import { componentTitle, inventoryEntryConnected, taxonomyIconUrl } from './inventory';

type Props = {
	inventory: ComponentInventoryResponse | undefined;
	taxonomy: TaxonomyResponse | undefined;
	topology: TopologyResponse | undefined;
	iconBase?: string;
	selectedId: string | null;
	onSelect: (id: string) => void;
};

export function ComponentsView(props: Props): JSX.Element {
	const [categoryId, setCategoryId] = useState<string | null>(null);
	const [kindFilter, setKindFilter] = useState<string | null>(null);
	const [packageFilter, setPackageFilter] = useState<string | null>(null);
	const [query, setQuery] = useState('');
	const [connectedOnly, setConnectedOnly] = useState(true);

	const categories = props.taxonomy?.component_taxonomy.categories ?? [];
	const packageOptions = useMemo(() => {
		const packages = new Set<string>();
		for (const entry of props.inventory?.components ?? []) {
			if (entry.structural_path?.package_id) {
				packages.add(entry.structural_path.package_id);
			}
		}
		return Array.from(packages).sort();
	}, [props.inventory]);

	const filtered = useMemo(() => {
		const q = query.trim().toLowerCase();
		return (props.inventory?.components ?? []).filter(entry => {
			if (connectedOnly && props.topology && !inventoryEntryConnected(entry, props.topology)) {
				return false;
			}
			if (categoryId && entry.classification?.category_id !== categoryId) {
				return false;
			}
			if (kindFilter && entry.model_kind !== kindFilter) {
				return false;
			}
			if (packageFilter && entry.structural_path?.package_id !== packageFilter) {
				return false;
			}
			if (!q) {
				return true;
			}
			return [
				entry.logical_component_id,
				entry.component_class,
				entry.subsystem,
				entry.structural_path?.package_id,
				entry.structural_path?.module_id,
				entry.classification?.subcategory_name,
			].filter(Boolean).join(' ').toLowerCase().includes(q);
		});
	}, [props.inventory, props.topology, categoryId, kindFilter, packageFilter, query, connectedOnly]);

	const grouped = useMemo(() => {
		const groups = new Map<string, ComponentInventoryEntry[]>();
		for (const entry of filtered) {
			const key = entry.classification?.category_name
				?? entry.subsystem?.replace(/_/g, ' ')
				?? entry.domain
				?? 'Uncategorized';
			const list = groups.get(key) ?? [];
			list.push(entry);
			groups.set(key, list);
		}
		return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
	}, [filtered]);

	const selected = filtered.find(c => c.logical_component_id === props.selectedId)
		?? props.inventory?.components.find(c => c.logical_component_id === props.selectedId)
		?? null;

	return (
		<div className="grid gap-6 xl:grid-cols-[1fr_300px]">
			<div className="space-y-4">
				<Card className="p-4">
					<div className="flex flex-wrap items-center gap-2">
						<Chip size="sm" variant="soft">{filtered.length} shown</Chip>
						<Chip size="sm" variant="soft">{props.inventory?.component_count ?? 0} total</Chip>
						<div className="ml-auto flex rounded-lg border border-separator p-0.5">
							<FilterToggle active={connectedOnly} onClick={() => setConnectedOnly(true)}>Connected</FilterToggle>
							<FilterToggle active={!connectedOnly} onClick={() => setConnectedOnly(false)}>All</FilterToggle>
						</div>
					</div>
					<div className="mt-3 flex flex-wrap gap-2">
						<FilterToggle active={categoryId === null} onClick={() => setCategoryId(null)}>All categories</FilterToggle>
						{categories.map(cat => (
							<FilterToggle key={cat.category_id} active={categoryId === cat.category_id} onClick={() => setCategoryId(cat.category_id)}>
								{cat.name}
							</FilterToggle>
						))}
						{['executable', 'parametric', 'digital'].map(kind => (
							<FilterToggle key={kind} active={kindFilter === kind} onClick={() => setKindFilter(kindFilter === kind ? null : kind)}>
								{kind}
							</FilterToggle>
						))}
						{packageOptions.map(packageId => (
							<FilterToggle key={packageId} active={packageFilter === packageId} onClick={() => setPackageFilter(packageFilter === packageId ? null : packageId)}>
								{packageId.replace(/^pkg_/, '')}
							</FilterToggle>
						))}
						<input
							type="search"
							placeholder="Search components…"
							value={query}
							onChange={event => setQuery(event.target.value)}
							className="ml-auto min-w-[180px] flex-1 rounded-lg border border-separator bg-surface px-3 py-1.5 text-sm sm:max-w-xs"
						/>
					</div>
				</Card>

				{grouped.map(([group, entries]) => (
					<section key={group} className="space-y-2">
						<h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{group}</h3>
						<div className="grid gap-3 sm:grid-cols-2">
							{entries.map(entry => {
								const icon = taxonomyIconUrl(props.iconBase, entry.classification);
								const selected = props.selectedId === entry.logical_component_id;
								const dimmed = !connectedOnly && !inventoryEntryConnected(entry, props.topology);
								return (
									<button
										key={entry.logical_component_id}
										type="button"
										onClick={() => props.onSelect(entry.logical_component_id)}
										className={`rounded-lg border p-3 text-left ${selected ? 'border-accent bg-accent/10' : 'border-separator bg-surface'} ${dimmed ? 'opacity-60' : ''}`}
									>
										<div className="flex items-start gap-2">
											{icon ? <img src={icon} alt="" className="size-6 brightness-110" /> : null}
											<div className="min-w-0">
												<p className="truncate text-sm font-semibold capitalize">{componentTitle(entry)}</p>
												<p className="truncate text-xs text-muted">{entry.component_class} · {entry.model_kind ?? entry.domain ?? '—'}</p>
												{entry.structural_path?.module_id ? (
													<p className="mt-1 font-mono text-[11px] text-muted">{entry.structural_path.module_id}</p>
												) : entry.source_file ? (
													<p className="mt-1 font-mono text-[11px] text-muted">{entry.source_file}</p>
												) : null}
											</div>
										</div>
									</button>
								);
							})}
						</div>
					</section>
				))}

				{filtered.length === 0 ? (
					<Card className="p-8 text-center text-sm text-muted">No components match the current filters.</Card>
				) : null}
			</div>

			<Card className="h-fit p-4">
				{selected ? (
					<>
						<p className="text-sm font-semibold capitalize">{componentTitle(selected)}</p>
						<p className="text-xs text-muted">{selected.component_class}</p>
						<dl className="mt-3 space-y-1 text-xs">
							<div className="flex justify-between gap-2"><dt className="text-muted">Kind</dt><dd>{selected.model_kind ?? '—'}</dd></div>
							<div className="flex justify-between gap-2"><dt className="text-muted">Subsystem</dt><dd>{selected.subsystem ?? '—'}</dd></div>
							<div className="flex justify-between gap-2"><dt className="text-muted">Package</dt><dd>{selected.structural_path?.package_id?.replace(/^pkg_/, '') ?? '—'}</dd></div>
							<div className="flex justify-between gap-2"><dt className="text-muted">Module</dt><dd>{selected.structural_path?.module_id ?? '—'}</dd></div>
							<div className="flex justify-between gap-2"><dt className="text-muted">Source</dt><dd className="truncate font-mono">{selected.source_file ?? '—'}</dd></div>
						</dl>
					</>
				) : (
					<p className="text-sm text-muted">Select a component to inspect its classification and structural path.</p>
				)}
			</Card>
		</div>
	);
}

function FilterToggle(props: { active: boolean; onClick: () => void; children: ReactNode }): JSX.Element {
	return (
		<button
			type="button"
			onClick={props.onClick}
			className={`rounded-lg px-3 py-1.5 text-xs capitalize transition-colors ${
				props.active ? 'bg-accent/15 text-accent' : 'bg-surface text-muted hover:text-foreground'
			}`}
		>
			{props.children}
		</button>
	);
}
