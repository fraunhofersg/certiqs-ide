import { Button, Chip, Input, Label, TextField } from '@heroui/react';
import { useEffect, useMemo, useState } from 'react';
import type { ApiResponse, ApplicableEA, Overrides } from '../lib/applicabilityTypes';
import { chipMatches } from '../../../src/chipFilters';
import { MODULE_ORDER } from '../lib/modules';
import { normalizeComponentTerms } from '../lib/qkd/componentTerms';
import { api, rpc } from '../hostRpc';
import { surfaceSystemId, useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

const OVERRIDE_FIELDS: Array<{ key: keyof Overrides; label: string }> = [
	{ key: 'doubleClickHandling', label: 'Double-click handling' },
	{ key: 'basisChoice', label: 'Basis choice' },
	{ key: 'deployment', label: 'Deployment' },
	{ key: 'opticalPathDirection', label: 'Optical path' },
	{ key: 'sourceType', label: 'Source type' },
	{ key: 'localOscillatorType', label: 'Local oscillator' },
	{ key: 'phaseRandomisationMethod', label: 'Phase randomisation' },
	{ key: 'reconciliationAlgorithm', label: 'Reconciliation' },
];

export function Applicability(): JSX.Element {
	const state = useQdbState();
	const [systems, setSystems] = useState<Array<{ id: number; name: string }>>([]);
	const [systemId, setSystemId] = useState<number | ''>(surfaceSystemId() ?? state.selectedSystemId ?? '');
	const [tab, setTab] = useState<'attacks' | 'eas'>('attacks');
	const [overrides, setOverrides] = useState<Overrides>({});
	const [data, setData] = useState<ApiResponse | undefined>();
	const [eas, setEas] = useState<ApplicableEA[]>([]);
	const [error, setError] = useState('');
	const [modules, setModules] = useState<string[]>([]);
	const [showNoScope, setShowNoScope] = useState(false);

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		api<Array<{ id: number; name: string }>>('GET', '/internal/systems')
			.then(setSystems)
			.catch(err => setError((err as Error).message));
	}, [state.api]);

	useEffect(() => {
		if (state.api !== 'ready' || !systemId) {
			return;
		}
		void rpc('setSelectedSystem', { systemId });
		const handle = setTimeout(() => {
			const query: Record<string, string | boolean> = {};
			for (const [key, value] of Object.entries(overrides)) {
				if (value !== undefined && value !== '') {
					query[key] = value as string | boolean;
				}
			}
			api<ApiResponse>('GET', `/internal/qkd/systems/${systemId}/applicability`, { query })
				.then(setData)
				.catch(err => setError((err as Error).message));
			api<ApplicableEA[]>('GET', `/internal/qkd/systems/${systemId}/applicable-eas`, { query })
				.then(setEas)
				.catch(err => setError((err as Error).message));
		}, 200);
		return () => clearTimeout(handle);
	}, [state.api, systemId, overrides]);

	const dirty = Object.values(overrides).some(value => value !== undefined && value !== '');
	const attacks = useMemo(() => {
		const rows = data?.applicable ?? [];
		return rows.filter(row => chipMatches(row, { encodings: [], architectures: [], modules, components: [] }, normalizeComponentTerms));
	}, [data, modules]);

	return (
		<Page
			title="Applicability"
			subtitle="What-if overrides are query-time only. Clearing restores stored features."
		>
			<ErrorText error={error} />
			<div className="qdb-row">
				<select
					className="rounded-md border border-separator bg-surface px-3 py-2"
					value={systemId}
					onChange={event => setSystemId(event.target.value ? Number(event.target.value) : '')}
				>
					<option value="">Select a visible system</option>
					{systems.map(system => (
						<option key={system.id} value={system.id}>{system.name}</option>
					))}
				</select>
				<Button size="sm" variant={tab === 'attacks' ? 'primary' : 'outline'} onPress={() => setTab('attacks')}>Attacks</Button>
				<Button size="sm" variant={tab === 'eas' ? 'primary' : 'outline'} onPress={() => setTab('eas')}>EAs</Button>
				{dirty ? <Chip size="sm" variant="soft">What-if modified</Chip> : null}
				<Button size="sm" variant="ghost" onPress={() => setOverrides({})}>Clear overrides</Button>
			</div>
			<div className="grid gap-2 md:grid-cols-2">
				{OVERRIDE_FIELDS.map(field => (
					<TextField key={field.key}>
						<Label>{field.label}</Label>
						<Input
							value={String(overrides[field.key] ?? '')}
							onChange={event => setOverrides(current => ({ ...current, [field.key]: event.target.value || undefined }))}
						/>
					</TextField>
				))}
			</div>
			{tab === 'attacks' ? (
				<>
					<div className="qdb-row">
						{MODULE_ORDER.map(module => (
							<Button
								key={module}
								size="sm"
								variant={modules.includes(module) ? 'primary' : 'outline'}
								onPress={() => setModules(current => current.includes(module) ? current.filter(item => item !== module) : [...current, module])}
							>
								{module}
							</Button>
						))}
						<Button size="sm" variant="ghost" onPress={() => setShowNoScope(value => !value)}>
							{showNoScope ? 'Hide no-scope' : 'Show no-scope'}
						</Button>
					</div>
					<Bucket title={`Applicable (${attacks.length})`} rows={attacks.map(row => `${row.name} · ${row.attackRating ?? '—'} · ${row.module ?? ''}`)} />
					<Bucket title={`Unevaluated (${data?.unevaluated.length ?? 0})`} rows={(data?.unevaluated ?? []).map(row => `${row.name} — missing ${row.missing.join(', ')}`)} />
					<Bucket title={`Cross-family unknown (${data?.crossFamilyUnknown.length ?? 0})`} rows={(data?.crossFamilyUnknown ?? []).map(row => row.name)} />
					<Bucket title={`Excluded (${data?.excluded.length ?? 0})`} rows={(data?.excluded ?? []).map(row => `${row.name} — ${row.reason}`)} />
					<Bucket title={`Conditions failed (${data?.conditionsFailed.length ?? 0})`} rows={(data?.conditionsFailed ?? []).map(row => `${row.name} — ${row.reason}`)} />
					{showNoScope ? <Bucket title={`No scope match (${data?.noScopeMatch.length ?? 0})`} rows={(data?.noScopeMatch ?? []).map(row => row.name)} /> : null}
				</>
			) : (
				<table className="qdb-table">
					<thead>
						<tr>
							<th>Code</th>
							<th>Name</th>
							<th>Score</th>
							<th>Covered attacks</th>
						</tr>
					</thead>
					<tbody>
						{eas.map(row => (
							<tr key={row.code}>
								<td>{row.code}</td>
								<td>{row.name}</td>
								<td>{row.score}</td>
								<td>{row.applicableAttacks.map(attack => attack.name).join(', ')}</td>
							</tr>
						))}
					</tbody>
				</table>
			)}
		</Page>
	);
}

function Bucket(props: { title: string; rows: string[] }): JSX.Element {
	return (
		<section>
			<h2 className="text-sm font-semibold">{props.title}</h2>
			{props.rows.length ? (
				<ul className="qdb-muted list-disc pl-5">
					{props.rows.map(row => <li key={row}>{row}</li>)}
				</ul>
			) : <p className="qdb-muted">None</p>}
		</section>
	);
}
