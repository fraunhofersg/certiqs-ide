import { Button } from '@heroui/react';
import { Panel } from '@xyflow/react';
import type { TopologyResponse } from '../../../src/apiTypes';
import { DETAIL_LEVELS, isPackageTopology, type DetailLevel } from './hierarchy-ui';
import type { ViewMode } from './layout';

const MODES: { id: ViewMode; label: string; hint: string }[] = [
	{ id: 'hierarchy', label: 'Package hierarchy', hint: 'Schema 4.0 node → device → KMS drill-down' },
	{ id: 'full', label: 'Simulation graph', hint: 'Flat adapter view used by the physics engine' },
	{ id: 'system', label: 'System overview', hint: 'Lifted subsystem boundaries' },
];

export function TopologyViewModes(props: {
	topology: TopologyResponse;
	viewMode: ViewMode;
	onViewModeChange: (mode: ViewMode) => void;
	detailLevel?: DetailLevel;
	onDetailLevelChange?: (level: DetailLevel) => void;
}): JSX.Element {
	const hasHierarchy = Boolean(props.topology.hierarchy?.length);
	const packageLayout = isPackageTopology(props.topology);
	const visibleModes = MODES.filter(mode => mode.id !== 'hierarchy' || hasHierarchy);
	const showDetail = props.viewMode === 'hierarchy' && hasHierarchy && Boolean(props.onDetailLevelChange);

	return (
		<div className="flex flex-col gap-2">
			<div className="flex flex-wrap items-center gap-2">
				<div className="flex rounded-lg border border-separator p-0.5">
					{visibleModes.map(mode => (
						<button
							key={mode.id}
							type="button"
							title={mode.hint}
							onClick={() => props.onViewModeChange(mode.id)}
							className={`rounded-md px-3 py-1.5 text-xs transition-colors ${
								props.viewMode === mode.id ? 'bg-accent/15 text-accent' : 'text-muted hover:text-foreground'
							}`}
						>
							{mode.label}
						</button>
					))}
				</div>
				{showDetail ? (
					<div className="flex items-center gap-1.5">
						<span className="text-[10px] font-semibold uppercase tracking-wide text-muted/70">Detail</span>
						<div className="flex rounded-lg border border-separator p-0.5">
							{DETAIL_LEVELS.map(level => (
								<button
									key={level.id}
									type="button"
									title={level.hint}
									onClick={() => props.onDetailLevelChange?.(level.id)}
									className={`rounded-md px-2.5 py-1.5 text-xs transition-colors ${
										props.detailLevel === level.id ? 'bg-accent/15 text-accent' : 'text-muted hover:text-foreground'
									}`}
								>
									{level.label}
								</button>
							))}
						</div>
					</div>
				) : null}
			</div>
			<p className="text-[11px] text-muted">
				{props.viewMode === 'hierarchy'
					? packageLayout
						? 'Double-click a frame to zoom in; use the flow navigation to go back up.'
						: 'Double-click a frame to zoom in; use the flow navigation to go back up.'
					: props.viewMode === 'full'
						? 'Simulation graph: flat subsystem wiring produced by the topology adapter for NetSquid.'
						: 'System overview: subsystem boundaries with lifted cross-links.'}
			</p>
		</div>
	);
}

export function TopologyHierarchyBreadcrumb(props: {
	breadcrumb: Array<{ id: string; label: string }>;
	focusId: string | null;
	canDrillSelected: boolean;
	selectedLabel?: string | null;
	onNavigate: (groupId: string) => void;
	onDrill: () => void;
}): JSX.Element | null {
	if (props.breadcrumb.length === 0) {
		return null;
	}
	return (
		<nav className="flex flex-wrap items-center gap-1 text-xs text-muted">
			{props.breadcrumb.map((crumb, index) => (
				<span key={crumb.id} className="inline-flex items-center gap-1">
					{index > 0 ? <span className="text-muted/60">/</span> : null}
					<button
						type="button"
						onClick={() => props.onNavigate(crumb.id)}
						className={`rounded px-1.5 py-0.5 capitalize transition-colors ${
							crumb.id === props.focusId
								? 'bg-accent/12 font-medium text-accent'
								: 'hover:bg-surface hover:text-foreground'
						}`}
					>
						{crumb.label}
					</button>
				</span>
			))}
			{props.canDrillSelected && props.selectedLabel ? (
				<Button size="sm" variant="ghost" className="ml-2 h-7 min-h-0 text-xs" onPress={props.onDrill}>
					Drill into {props.selectedLabel}
				</Button>
			) : null}
		</nav>
	);
}

export function TopologyFlowNavigation(props: {
	breadcrumb: Array<{ id: string; label: string }>;
	focusId: string | null;
	canGoUp: boolean;
	onNavigate: (groupId: string) => void;
	onGoUp: () => void;
}): JSX.Element | null {
	if (props.breadcrumb.length === 0) {
		return null;
	}
	return (
		<Panel position="top-left" className="!m-3 !rounded-lg !border !border-separator !bg-surface/95 !p-2 !shadow-sm">
			<div className="flex flex-wrap items-center gap-1.5">
				<Button size="sm" variant="ghost" isDisabled={!props.canGoUp} className="h-7 min-h-0 px-2 text-xs" onPress={props.onGoUp}>
					← Up
				</Button>
				<nav className="flex flex-wrap items-center gap-0.5 text-[11px] text-muted">
					{props.breadcrumb.map((crumb, index) => (
						<span key={crumb.id} className="inline-flex items-center gap-0.5">
							{index > 0 ? <span className="text-muted/50">/</span> : null}
							<button
								type="button"
								onClick={() => props.onNavigate(crumb.id)}
								className={`max-w-[9rem] truncate rounded px-1 py-0.5 capitalize ${
									crumb.id === props.focusId ? 'bg-accent/12 font-medium text-accent' : 'hover:text-foreground'
								}`}
								title={crumb.label}
							>
								{crumb.label}
							</button>
						</span>
					))}
				</nav>
			</div>
		</Panel>
	);
}

export function TopologyLegend(): JSX.Element {
	const items = [
		['#6366f1', 'System'],
		['#8b5cf6', 'QKD node'],
		['#0ea5e9', 'Device'],
		['#10b981', 'KMS'],
		['#f59e0b', 'Module'],
		['#a78bfa', 'Quantum'],
		['#fbbf24', 'Digital'],
	];
	return (
		<div className="flex flex-wrap gap-2 text-[10px] text-muted">
			{items.map(([color, label]) => (
				<span key={label} className="inline-flex items-center gap-1">
					<span className="size-2 rounded-full" style={{ backgroundColor: color }} />
					{label}
				</span>
			))}
		</div>
	);
}
