import { Button, Input, Label, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import { api, rpc } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

type Source = { id: number; label: string; blob_url: string; subclause_count: number };

export function Documents(): JSX.Element {
	const state = useQdbState();
	const [rows, setRows] = useState<Source[]>([]);
	const [error, setError] = useState('');
	const [label, setLabel] = useState('');
	const [blobUrl, setBlobUrl] = useState('');

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		api<Source[]>('GET', '/internal/document-sources')
			.then(setRows)
			.catch(err => setError((err as Error).message));
	}, [state.api]);

	async function register(): Promise<void> {
		try {
			await api('POST', '/internal/document-sources', { body: { label, blob_url: blobUrl, subclauses: [] } });
			setLabel('');
			setBlobUrl('');
			setRows(await api<Source[]>('GET', '/internal/document-sources'));
		} catch (err) {
			setError((err as Error).message);
		}
	}

	async function pick(): Promise<void> {
		const picked = await rpc<{ label?: string; blobUrl?: string; cancelled?: boolean }>('pickPdf');
		if (picked.cancelled || !picked.blobUrl) {
			return;
		}
		setBlobUrl(picked.blobUrl);
		if (picked.label && !label) {
			setLabel(picked.label);
		}
	}

	return (
		<Page title="Document sources" subtitle="Admin registry. PDFs live in extension global storage; FastAPI stores the file URL.">
			<ErrorText error={error} />
			{!state.isAdmin ? <p className="qdb-muted">Admin principal required to register sources.</p> : null}
			<table className="qdb-table">
				<thead>
					<tr>
						<th>Label</th>
						<th>URL</th>
						<th>Subclauses</th>
					</tr>
				</thead>
				<tbody>
					{rows.map(row => (
						<tr key={row.id}>
							<td>{row.label}</td>
							<td className="qdb-muted">{row.blob_url}</td>
							<td>{row.subclause_count}</td>
						</tr>
					))}
				</tbody>
			</table>
			{state.isAdmin ? (
				<section className="flex max-w-lg flex-col gap-2">
					<TextField><Label>Label</Label><Input value={label} onChange={event => setLabel(event.target.value)} /></TextField>
					<TextField><Label>Storage URL</Label><Input value={blobUrl} onChange={event => setBlobUrl(event.target.value)} /></TextField>
					<div className="qdb-row">
						<Button size="sm" variant="outline" onPress={() => void pick()}>Pick PDF</Button>
						<Button size="sm" variant="primary" isDisabled={!label || !blobUrl} onPress={() => void register()}>Register</Button>
					</div>
				</section>
			) : null}
		</Page>
	);
}
