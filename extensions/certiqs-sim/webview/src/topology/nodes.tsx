import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import { memo } from 'react';
import type { TwinNodeData } from './build-flow';
import { NODE_WIDTH } from './layout';
import { DEFAULT_IN_HANDLE, DEFAULT_OUT_HANDLE, NODE_TYPE_LABELS, deploymentRoleLabel } from './topology-ui';

type FlowNode = Node<TwinNodeData, 'twinNode' | 'twinGroup'>;

function groupFrameClass(role?: string | null, groupKind?: string | null): string {
	const kind = groupKind ?? role;
	if (kind === 'qkd_device') {
		return 'twin-group-frame twin-group-frame--device';
	}
	if (kind === 'qkd_node') {
		return 'twin-group-frame twin-group-frame--node';
	}
	if (kind === 'kms' || kind === 'kms_component') {
		return 'twin-group-frame twin-group-frame--kms';
	}
	if (kind === 'post_processing') {
		return 'twin-group-frame twin-group-frame--post';
	}
	if (kind === 'domain') {
		return 'twin-group-frame twin-group-frame--domain';
	}
	if (kind === 'software_group' || kind === 'module') {
		return 'twin-group-frame twin-group-frame--module';
	}
	if (kind === 'network_coordination') {
		return 'twin-group-frame twin-group-frame--coord';
	}
	if (kind === 'qkd_system') {
		return 'twin-group-frame twin-group-frame--system';
	}
	return 'twin-group-frame twin-group-frame--default';
}

function TwinNodeComponent({ data, selected }: NodeProps<FlowNode>) {
	const active = selected || data.highlighted;
	const compact = data.compact ?? false;
	const width = data.nodeWidth ?? NODE_WIDTH;
	return (
		<div
			className={`twin-flow-node relative rounded-xl border bg-surface shadow-md ${compact ? 'px-2 py-2' : 'px-3 py-2.5'} ${
				active ? 'border-accent shadow-lg ring-2 ring-accent/40' : 'border-separator/90'
			}`}
			style={{ width, borderLeftWidth: 4, borderLeftColor: data.accent, minHeight: compact ? 72 : 96 }}
		>
			<Handle type="target" position={Position.Left} id={DEFAULT_IN_HANDLE} className="!size-2 !border-0 !bg-accent" />
			<Handle type="source" position={Position.Right} id={DEFAULT_OUT_HANDLE} className="!size-2 !border-0 !bg-accent" />
			<div className={`flex items-start ${compact ? 'gap-1.5' : 'gap-2.5'}`}>
				{!compact ? (
					<div className="flex size-9 shrink-0 items-center justify-center rounded-lg p-1.5" style={{ backgroundColor: `${data.accent}22` }}>
						{data.iconUrl ? (
							<img src={data.iconUrl} alt="" className="size-6 brightness-110 contrast-125" />
						) : (
							<span className="size-2 rounded-full" style={{ backgroundColor: data.accent }} />
						)}
					</div>
				) : null}
				<div className="min-w-0 flex-1">
					<p className={`truncate font-semibold capitalize leading-tight ${compact ? 'text-[11px]' : 'text-sm'}`}>{data.label}</p>
					{!compact ? (
						<>
							<p className="truncate text-[11px] text-muted">{data.componentClass}</p>
							<span
								className="mt-1 inline-block rounded-md px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide"
								style={{ backgroundColor: `${data.accent}28`, color: data.accent }}
							>
								{NODE_TYPE_LABELS[data.nodeType] ?? data.nodeType}
							</span>
						</>
					) : null}
				</div>
			</div>
		</div>
	);
}

function TwinGroupComponent({ data, selected }: NodeProps<FlowNode>) {
	const active = selected || data.highlighted;
	const nested = data.nested ?? false;
	const depth = data.frameDepth ?? 0;
	const minimal = data.minimalFrame ?? data.groupKind === 'domain';
	const roleBadge = deploymentRoleLabel(data.deploymentRole);
	const headerText = minimal
		? 'text-[8px] font-medium normal-case tracking-wide'
		: !nested || depth <= 0
			? 'text-xs'
			: depth === 1
				? 'text-[11px]'
				: 'text-[10px]';
	return (
		<div
			className={`relative h-full w-full overflow-visible rounded-lg ${groupFrameClass(data.deploymentRole, data.groupKind)} ${active ? 'twin-group-frame--active' : ''}`}
			data-nested={nested ? 'true' : undefined}
			data-minimal={minimal ? 'true' : undefined}
		>
			<Handle type="target" position={Position.Left} id={DEFAULT_IN_HANDLE} className="!size-2 !border-0 !bg-accent" />
			<Handle type="source" position={Position.Right} id={DEFAULT_OUT_HANDLE} className="!size-2 !border-0 !bg-accent" />
			<div
				className={`nodrag nopan flex items-center gap-1.5 rounded-t-[7px] px-2.5 font-semibold capitalize ${minimal ? 'py-0.5' : nested ? 'py-1.5' : 'py-2.5'} ${headerText}`}
				style={minimal
					? { backgroundColor: 'transparent', color: 'var(--muted)' }
					: { backgroundColor: `${data.accent}20`, color: data.accent }}
			>
				{!minimal ? (
					data.iconUrl
						? <img src={data.iconUrl} alt="" className={nested ? 'size-4 brightness-110' : 'size-5 brightness-110'} />
						: <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: data.accent }} />
				) : null}
				<span className="min-w-0 flex-1 truncate">{data.label}</span>
				{data.packageId && !minimal ? (
					<span className="shrink-0 rounded bg-surface/80 px-1 py-0.5 font-mono text-[9px] text-muted">
						{data.packageId.replace(/^pkg_/, '')}
					</span>
				) : null}
				{roleBadge && !nested && !minimal ? (
					<span className="shrink-0 rounded-md bg-surface/80 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted">
						{roleBadge}
					</span>
				) : null}
			</div>
			{data.collapsedSummary ? (
				<span className="pointer-events-none absolute bottom-2 left-2.5 text-[9px] font-medium uppercase tracking-wide text-muted/80">
					{data.collapsedSummary}
				</span>
			) : null}
		</div>
	);
}

export const topologyNodeTypes = {
	twinNode: memo(TwinNodeComponent),
	twinGroup: memo(TwinGroupComponent),
};
