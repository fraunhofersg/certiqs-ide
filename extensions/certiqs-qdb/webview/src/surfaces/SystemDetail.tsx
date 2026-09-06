import { Button, Chip } from '@heroui/react';
import { useEffect, useState } from 'react';
import { api, openPage, rpc } from '../hostRpc';
import { surfaceSystemId, useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

type SystemDetail = {
	id: number;
	name: string;
	manufacturer: string | null;
	toe_boundary: string | null;
	is_public?: boolean;
	user_id?: string;
	encoding_name?: string | null;
	architecture_name?: string | null;
	created_at?: string;
	double_click_handling?: string | null;
	basis_choice?: string | null;
	deployment?: string | null;
	protocols?: Array<{ id: number; name: string; family?: string; is_primary?: boolean }>;
	modules?: Array<{
		id: number;
		name: string;
		module_type: string;
		components: Array<{
			instance_name: string | null;
			name: string;
			vendor: string | null;
			model: string | null;
			component_type: string;
			parameters: Array<{ key: string; value: string; unit: string | null; state?: string }>;
			characterisedParameters?: Array<{ key: string; value: string; unit: string | null }>;
		}>;
	}>;
	systemPp?: Array<{ ppTypeName: string; annotation: string | null }>;
	connections?: Array<{ from_component: string | null; to_component: string | null; medium: string | null }>;
	systemCountermeasures?: Array<{ name: string; module_type_name: string }>;
};

export function SystemDetail(): JSX.Element {
	const state = useQdbState();
	const systemId = surfaceSystemId() ?? state.selectedSystemId;
	const [system, setSystem] = useState<SystemDetail | undefined>();
	const [paramState, setParamState] = useState<'ideal' | 'characterised'>('ideal');
	const [error, setError] = useState('');

	useEffect(() => {
		if (state.api !== 'ready' || !systemId) {
			return;
		}
		api<SystemDetail>('GET', `/internal/systems/${systemId}`)
			.then(setSystem)
			.catch(err => setError((err as Error).message));
	}, [state.api, systemId]);

	async function toggleVisibility(): Promise<void> {
		if (!system) {
			return;
		}
		try {
			await api('PATCH', `/internal/systems/${system.id}/visibility`, {
				body: { isPublic: !system.is_public },
			});
			setSystem({ ...system, is_public: !system.is_public });
		} catch (err) {
			setError((err as Error).message);
		}
	}

	async function exportZip(): Promise<void> {
		if (!system) {
			return;
		}
		try {
			const prepare = await api<{ missing: unknown[] }>('GET', `/internal/export/${system.id}/prepare`);
			if (prepare.missing?.length) {
				setError(`Export needs ${prepare.missing.length} parameter(s). Fill characterised values, then retry.`);
				return;
			}
			await rpc('exportZip', { systemId: system.id, paramValues: {} });
		} catch (err) {
			setError((err as Error).message);
		}
	}

	if (!systemId) {
		return <Page title="System"><p className="qdb-muted">Pick a system from the list.</p></Page>;
	}

	return (
		<Page
			title={system?.name ?? `System ${systemId}`}
			subtitle={[system?.manufacturer, system?.encoding_name, system?.architecture_name].filter(Boolean).join(' · ')}
			actions={
				<>
					<Button size="sm" variant="outline" onPress={() => openPage('applicability', systemId)}>Applicability</Button>
					<Button size="sm" variant="outline" onPress={() => void exportZip()}>Export YAML</Button>
					{system && (state.isAdmin || system.user_id === state.userId) ? (
						<Button size="sm" variant="ghost" onPress={() => void toggleVisibility()}>
							{system.is_public ? 'Make private' : 'Make public'}
						</Button>
					) : null}
				</>
			}
		>
			<ErrorText error={error} />
			{system ? (
				<>
					<div className="qdb-row">
						<Chip size="sm" variant="soft">TOE {system.toe_boundary ?? '—'}</Chip>
						{system.protocols?.map(protocol => (
							<Chip key={protocol.id} size="sm" variant={protocol.is_primary ? 'secondary' : 'soft'}>{protocol.name}</Chip>
						))}
					</div>
					<div className="qdb-row">
						<Button size="sm" variant={paramState === 'ideal' ? 'primary' : 'outline'} onPress={() => setParamState('ideal')}>Ideal</Button>
						<Button size="sm" variant={paramState === 'characterised' ? 'primary' : 'outline'} onPress={() => setParamState('characterised')}>Characterised</Button>
					</div>
					{(system.modules ?? []).filter(module => module.module_type !== 'POST_PROCESSING' && module.module_type !== 'PP').map(module => (
						<section key={module.id} className="flex flex-col gap-2">
							<h2 className="text-sm font-semibold">{module.name} · {module.module_type}</h2>
							<table className="qdb-table">
								<thead>
									<tr>
										<th>Instance</th>
										<th>Type</th>
										<th>Vendor / model</th>
										<th>Parameters</th>
									</tr>
								</thead>
								<tbody>
									{module.components.map(component => {
										const params = paramState === 'characterised' ? (component.characterisedParameters ?? []) : component.parameters;
										return (
											<tr key={component.instance_name ?? component.name}>
												<td>{component.instance_name ?? component.name}</td>
												<td>{component.component_type}</td>
												<td>{[component.vendor, component.model].filter(Boolean).join(' ') || '—'}</td>
												<td>{params.map(param => `${param.key}=${param.value}${param.unit ? ` ${param.unit}` : ''}`).join(', ') || '—'}</td>
											</tr>
										);
									})}
								</tbody>
							</table>
						</section>
					))}
					<section>
						<h2 className="text-sm font-semibold">Post-processing</h2>
						<ul className="qdb-muted list-disc pl-5">
							{(system.systemPp ?? []).map(stage => (
								<li key={stage.ppTypeName}>{stage.ppTypeName}{stage.annotation ? ` — ${stage.annotation}` : ''}</li>
							))}
						</ul>
					</section>
					<section>
						<h2 className="text-sm font-semibold">Connections</h2>
						<ul className="qdb-muted list-disc pl-5">
							{(system.connections ?? []).map((connection, index) => (
								<li key={index}>{connection.from_component} → {connection.to_component} ({connection.medium})</li>
							))}
						</ul>
					</section>
					<section>
						<h2 className="text-sm font-semibold">Installed countermeasures</h2>
						<ul className="qdb-muted list-disc pl-5">
							{(system.systemCountermeasures ?? []).map((cm, index) => (
								<li key={index}>{cm.name} · {cm.module_type_name}</li>
							))}
						</ul>
					</section>
				</>
			) : <p className="qdb-muted">Loading…</p>}
		</Page>
	);
}
