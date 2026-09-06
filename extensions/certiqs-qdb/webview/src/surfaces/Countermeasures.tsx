import { Chip } from '@heroui/react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

type CmRow = {
	id: number;
	name: string;
	description: string | null;
	countermeasure_type: string;
	module: string | null;
	vuln_link_count?: number;
};

const GROUPS = ['Hardware', 'Software', 'Hardware + Software'];

export function Countermeasures(): JSX.Element {
	const state = useQdbState();
	const [rows, setRows] = useState<CmRow[]>([]);
	const [error, setError] = useState('');
	const grouped = useMemo(() => {
		const map = new Map<string, CmRow[]>();
		for (const group of GROUPS) {
			map.set(group, []);
		}
		for (const row of rows) {
			const key = GROUPS.includes(row.countermeasure_type) ? row.countermeasure_type : row.countermeasure_type;
			const list = map.get(key) ?? [];
			list.push(row);
			map.set(key, list);
		}
		return map;
	}, [rows]);

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		api<CmRow[]>('GET', '/internal/countermeasures')
			.then(setRows)
			.catch(err => setError((err as Error).message));
	}, [state.api]);

	return (
		<Page title="Countermeasures" subtitle="Null module displays as System-Wide. Grouped by countermeasure_type.">
			<ErrorText error={error} />
			{[...grouped.entries()].map(([group, items]) => (
				<section key={group} className="flex flex-col gap-2">
					<h2 className="text-sm font-semibold">{group} ({items.length})</h2>
					<table className="qdb-table">
						<thead>
							<tr>
								<th>Name</th>
								<th>Modules</th>
								<th>Vuln links</th>
							</tr>
						</thead>
						<tbody>
							{items.map(item => (
								<tr key={item.id}>
									<td>{item.name}</td>
									<td><Chip size="sm" variant="soft">{item.module ?? 'System-Wide'}</Chip></td>
									<td>{item.vuln_link_count ?? 0}</td>
								</tr>
							))}
						</tbody>
					</table>
				</section>
			))}
		</Page>
	);
}
