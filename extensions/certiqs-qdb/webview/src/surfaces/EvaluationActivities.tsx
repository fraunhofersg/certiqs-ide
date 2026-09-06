import { Button, Input, Label, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import { PARAMETER_TYPES } from '../lib/qkd/eaParameterEnums';
import { api, rpc } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

type EARow = {
	id: number;
	code: string;
	name: string;
	description: string | null;
	subclause: string | null;
	is_iso_mandated?: boolean | null;
};

export function EvaluationActivities(): JSX.Element {
	const state = useQdbState();
	const [rows, setRows] = useState<EARow[]>([]);
	const [error, setError] = useState('');
	const [code, setCode] = useState('');
	const [name, setName] = useState('');
	const [description, setDescription] = useState('');

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		api<EARow[]>('GET', '/internal/evaluation-activities')
			.then(setRows)
			.catch(err => setError((err as Error).message));
	}, [state.api]);

	async function create(): Promise<void> {
		try {
			await api('POST', '/internal/evaluation-activities', { body: { code, name, description } });
			setCode('');
			setName('');
			setDescription('');
			setRows(await api<EARow[]>('GET', '/internal/evaluation-activities'));
		} catch (err) {
			setError((err as Error).message);
		}
	}

	async function openReference(eaCode: string): Promise<void> {
		try {
			const result = await api<{ url: string }>('GET', `/internal/evaluation-activities/${encodeURIComponent(eaCode)}/reference`);
			await rpc('openExternal', { url: result.url });
		} catch (err) {
			setError((err as Error).message);
		}
	}

	return (
		<Page title="Evaluation activities" subtitle={`${rows.length} catalogue rows. ISO-mandated flag shown when present.`}>
			<ErrorText error={error} />
			<table className="qdb-table">
				<thead>
					<tr>
						<th>Code</th>
						<th>Name</th>
						<th>ISO</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{rows.map(row => (
						<tr key={row.id}>
							<td>{row.code}</td>
							<td>{row.name}</td>
							<td>{row.is_iso_mandated === false ? 'no' : 'yes'}</td>
							<td><Button size="sm" variant="ghost" onPress={() => void openReference(row.code)}>Source</Button></td>
						</tr>
					))}
				</tbody>
			</table>
			{state.isAdmin ? (
				<section className="flex max-w-lg flex-col gap-2">
					<h2 className="text-sm font-semibold">Create EA</h2>
					<TextField><Label>Code</Label><Input value={code} onChange={event => setCode(event.target.value)} /></TextField>
					<TextField><Label>Name</Label><Input value={name} onChange={event => setName(event.target.value)} /></TextField>
					<TextField><Label>Description</Label><Input value={description} onChange={event => setDescription(event.target.value)} /></TextField>
					<p className="qdb-muted">Parameter types: {PARAMETER_TYPES.join(', ')}</p>
					<Button size="sm" variant="primary" isDisabled={!code || !name} onPress={() => void create()}>Create</Button>
				</section>
			) : null}
		</Page>
	);
}
