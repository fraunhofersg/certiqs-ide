import { Button } from '@heroui/react';
import { useEffect, useState } from 'react';
import { api, openPage, rpc } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

type SystemRow = { id: number; name: string; manufacturer: string | null; toe_boundary: string | null };

export function Systems(): JSX.Element {
	const state = useQdbState();
	const [rows, setRows] = useState<SystemRow[]>([]);
	const [error, setError] = useState('');

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		api<SystemRow[]>('GET', '/internal/systems')
			.then(setRows)
			.catch(err => setError((err as Error).message));
	}, [state.api]);

	return (
		<Page
			title="Systems"
			subtitle="Visible systems (own or public), newest first."
			actions={<Button size="sm" variant="primary" onPress={() => openPage('wizard')}>New system</Button>}
		>
			<ErrorText error={error} />
			<table className="qdb-table">
				<thead>
					<tr>
						<th>Name</th>
						<th>Manufacturer</th>
						<th>TOE boundary</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{rows.map(row => (
						<tr key={row.id}>
							<td>{row.name}</td>
							<td>{row.manufacturer ?? '—'}</td>
							<td>{row.toe_boundary ?? '—'}</td>
							<td>
								<div className="qdb-row">
									<Button size="sm" variant="outline" onPress={() => {
										void rpc('setSelectedSystem', { systemId: row.id });
										openPage('system', row.id);
									}}>Open</Button>
									<Button size="sm" variant="ghost" onPress={() => {
										void rpc('setSelectedSystem', { systemId: row.id });
										openPage('applicability', row.id);
									}}>Applicability</Button>
								</div>
							</td>
						</tr>
					))}
				</tbody>
			</table>
			{state.api === 'ready' && !rows.length && !error ? <p className="qdb-muted">No systems yet.</p> : null}
		</Page>
	);
}
