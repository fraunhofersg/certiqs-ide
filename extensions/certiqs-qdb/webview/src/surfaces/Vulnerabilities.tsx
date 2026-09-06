import { Button, Input, Label, TextField } from '@heroui/react';
import { useEffect, useMemo, useState } from 'react';
import { chipMatches } from '../../../src/chipFilters';
import { MODULE_ORDER } from '../lib/modules';
import { ATTACK_RATINGS, ATTACK_TYPES, MODULES } from '../lib/qkd/attackEnums';
import { normalizeComponentTerms } from '../lib/qkd/componentTerms';
import { api, rpc } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

type VulnRow = {
	id: number;
	name: string;
	short_description: string | null;
	module: string | null;
	component: string | null;
	attack_type: string | null;
	attack_rating: string | null;
	category: string | null;
	encodings?: string[] | null;
};

export function Vulnerabilities(): JSX.Element {
	const state = useQdbState();
	const [rows, setRows] = useState<VulnRow[]>([]);
	const [modules, setModules] = useState<string[]>([]);
	const [error, setError] = useState('');
	const [name, setName] = useState('');
	const [shortDescription, setShortDescription] = useState('');

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		api<VulnRow[]>('GET', '/internal/vulnerabilities')
			.then(setRows)
			.catch(err => setError((err as Error).message));
	}, [state.api]);

	const visible = useMemo(
		() => rows.filter(row => chipMatches(row, { encodings: [], architectures: [], modules, components: [] }, normalizeComponentTerms)),
		[rows, modules],
	);
	const rated = visible.filter(row => row.attack_rating && row.attack_rating !== 'Vulnerability');
	const high = visible.filter(row => row.attack_rating === 'High' || row.attack_rating === 'Beyond High');

	async function create(): Promise<void> {
		try {
			await api('POST', '/internal/vulnerabilities', {
				body: { name, short_description: shortDescription },
			});
			setName('');
			setShortDescription('');
			setRows(await api<VulnRow[]>('GET', '/internal/vulnerabilities'));
		} catch (err) {
			setError((err as Error).message);
		}
	}

	async function openReference(id: number): Promise<void> {
		try {
			const result = await api<{ url: string }>('GET', `/internal/vulnerabilities/${id}/reference`);
			await rpc('openExternal', { url: result.url });
		} catch (err) {
			setError((err as Error).message);
		}
	}

	return (
		<Page title="Attacks" subtitle={`${visible.length} listed · ${rated.length} rated as attack · ${high.length} high / beyond-high`}>
			<ErrorText error={error} />
			<div className="qdb-row">
				{MODULE_ORDER.map(module => (
					<Button key={module} size="sm" variant={modules.includes(module) ? 'primary' : 'outline'} onPress={() => setModules(current => current.includes(module) ? current.filter(item => item !== module) : [...current, module])}>
						{module}
					</Button>
				))}
			</div>
			<table className="qdb-table">
				<thead>
					<tr>
						<th>Name</th>
						<th>Category</th>
						<th>Module</th>
						<th>Rating</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{visible.map(row => (
						<tr key={row.id}>
							<td>{row.name}</td>
							<td>{row.category ?? '—'}</td>
							<td>{row.module ?? '—'}</td>
							<td>{row.attack_rating ?? '—'}</td>
							<td><Button size="sm" variant="ghost" onPress={() => void openReference(row.id)}>Source</Button></td>
						</tr>
					))}
				</tbody>
			</table>
			{state.isAdmin ? (
				<section className="flex max-w-lg flex-col gap-2">
					<h2 className="text-sm font-semibold">Create vulnerability</h2>
					<TextField>
						<Label>Name</Label>
						<Input value={name} onChange={event => setName(event.target.value)} />
					</TextField>
					<TextField>
						<Label>Short description</Label>
						<Input value={shortDescription} onChange={event => setShortDescription(event.target.value)} />
					</TextField>
					<p className="qdb-muted">Enums: {MODULES.join(', ')} · {ATTACK_TYPES.join(', ')} · {ATTACK_RATINGS.join(', ')}</p>
					<Button size="sm" variant="primary" isDisabled={!name} onPress={() => void create()}>Create</Button>
				</section>
			) : null}
		</Page>
	);
}
