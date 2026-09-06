import { Button, Input, Label, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import {
	ConditionGroup,
	FieldMeta,
	SEARCH_DOMAIN_LABELS,
	SEARCH_DOMAINS,
	SearchDomain,
	countLeaves,
	decodeTreeParam,
	emptyCondition,
	emptyGroup,
	encodeTreeParam,
	getDepth,
	MAX_CONDITIONS,
	MAX_DEPTH,
} from '../lib/search';
import { api, openPage, rpc } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

const SUGGESTIONS = ['photon', 'intercept', 'side-channel', 'detector', 'timing'];

type QuickResult = {
	systems: Array<{ id: number; name: string; manufacturer: string | null }>;
	vulnerabilities: Array<{ id: number; name: string; short_description: string | null; category?: string | null }>;
};

export function Search(): JSX.Element {
	const state = useQdbState();
	const [mode, setMode] = useState<'quick' | 'advanced'>('quick');
	const [query, setQuery] = useState('');
	const [quick, setQuick] = useState<QuickResult>({ systems: [], vulnerabilities: [] });
	const [domain, setDomain] = useState<SearchDomain>('attacks');
	const [tree, setTree] = useState<ConditionGroup>(emptyGroup());
	const [fields, setFields] = useState<FieldMeta[]>([]);
	const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
	const [error, setError] = useState('');

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		void rpc<{ tree: string | ConditionGroup | null }>('loadSearchTree').then(stored => {
			if (!stored.tree) {
				return;
			}
			const decoded = typeof stored.tree === 'string' ? decodeTreeParam(stored.tree) : stored.tree;
			if (decoded.children.length) {
				setTree(decoded);
				setMode('advanced');
			}
		});
	}, [state.api]);

	useEffect(() => {
		if (state.api !== 'ready' || mode !== 'quick') {
			return;
		}
		const handle = setTimeout(() => {
			if (!query.trim()) {
				setQuick({ systems: [], vulnerabilities: [] });
				return;
			}
			api<QuickResult>('GET', '/internal/search/quick', { query: { q: query } })
				.then(setQuick)
				.catch(err => setError((err as Error).message));
		}, 250);
		return () => clearTimeout(handle);
	}, [query, mode, state.api]);

	useEffect(() => {
		if (state.api !== 'ready' || mode !== 'advanced') {
			return;
		}
		api<FieldMeta[]>('GET', '/internal/search/fields', { query: { domain } })
			.then(setFields)
			.catch(err => setError((err as Error).message));
	}, [domain, mode, state.api]);

	useEffect(() => {
		if (state.api !== 'ready' || mode !== 'advanced') {
			return;
		}
		const handle = setTimeout(() => {
			api<{ rows: Array<Record<string, unknown>> }>('POST', '/internal/search', {
				body: { domain, tree, limit: 25, offset: 0 },
			}).then(result => setRows(result.rows)).catch(err => setError((err as Error).message));
			void rpc('saveSearchTree', { tree: encodeTreeParam(tree) });
		}, 400);
		return () => clearTimeout(handle);
	}, [tree, domain, mode, state.api]);

	function addCondition(): void {
		if (countLeaves(tree) >= MAX_CONDITIONS) {
			return;
		}
		setTree({
			...tree,
			children: [...tree.children, emptyCondition()],
		});
	}

	function addGroup(): void {
		if (getDepth(tree) >= MAX_DEPTH) {
			return;
		}
		setTree({
			...tree,
			children: [...tree.children, emptyGroup(tree.combinator === 'AND' ? 'OR' : 'AND')],
		});
	}

	return (
		<Page title="Search" subtitle="Quick ILIKE, or advanced trees persisted in workspace state.">
			<ErrorText error={error} />
			<div className="qdb-row">
				<Button size="sm" variant={mode === 'quick' ? 'primary' : 'outline'} onPress={() => setMode('quick')}>Quick</Button>
				<Button size="sm" variant={mode === 'advanced' ? 'primary' : 'outline'} onPress={() => setMode('advanced')}>Advanced</Button>
			</div>
			{mode === 'quick' ? (
				<>
					<TextField>
						<Label>Query</Label>
						<Input value={query} onChange={event => setQuery(event.target.value)} placeholder="photon, intercept, detector…" />
					</TextField>
					{!query ? (
						<div className="qdb-row">
							{SUGGESTIONS.map(item => (
								<Button key={item} size="sm" variant="outline" onPress={() => setQuery(item)}>{item}</Button>
							))}
						</div>
					) : null}
					<section>
						<h2 className="text-sm font-semibold">Systems</h2>
						<ul className="qdb-muted list-disc pl-5">
							{quick.systems.map(row => (
								<li key={row.id}>
									<button className="underline" onClick={() => openPage('system', row.id)}>{row.name}</button>
									{row.manufacturer ? ` · ${row.manufacturer}` : ''}
								</li>
							))}
						</ul>
					</section>
					<section>
						<h2 className="text-sm font-semibold">Vulnerabilities</h2>
						<ul className="qdb-muted list-disc pl-5">
							{quick.vulnerabilities.map(row => (
								<li key={row.id}>{row.name}{row.category ? ` · ${row.category}` : ''}</li>
							))}
						</ul>
					</section>
				</>
			) : (
				<>
					<div className="qdb-row">
						{SEARCH_DOMAINS.map(item => (
							<Button
								key={item}
								size="sm"
								variant={domain === item ? 'primary' : 'outline'}
								onPress={() => {
									setDomain(item);
									setTree(emptyGroup());
								}}
							>
								{SEARCH_DOMAIN_LABELS[item]}
							</Button>
						))}
					</div>
					<div className="qdb-row">
						<Button size="sm" variant="outline" onPress={addCondition}>Add condition</Button>
						<Button size="sm" variant="outline" onPress={addGroup}>Add group</Button>
						<select
							className="rounded-md border border-separator bg-surface px-3 py-2"
							value={tree.combinator}
							onChange={event => setTree({ ...tree, combinator: event.target.value as 'AND' | 'OR' })}
						>
							<option value="AND">AND</option>
							<option value="OR">OR</option>
						</select>
					</div>
					{(tree.children.filter(child => child.kind === 'condition') as Array<{ id: string; field: string; operator: string; value: { text?: string } }>).map(child => (
						<div key={child.id} className="qdb-row">
							<select
								className="rounded-md border border-separator bg-surface px-3 py-2"
								value={child.field}
								onChange={event => setTree(current => ({
									...current,
									children: current.children.map(node => node.kind === 'condition' && node.id === child.id ? { ...node, field: event.target.value } : node),
								}))}
							>
								<option value="">Field</option>
								{fields.map(field => (
									<option key={field.key} value={field.key}>{field.group} / {field.label}</option>
								))}
							</select>
							<Input
								value={child.value.text ?? ''}
								onChange={event => setTree(current => ({
									...current,
									children: current.children.map(node => node.kind === 'condition' && node.id === child.id ? { ...node, value: { text: event.target.value } } : node),
								}))}
							/>
						</div>
					))}
					<table className="qdb-table">
						<thead>
							<tr>
								<th>Results ({rows.length})</th>
							</tr>
						</thead>
						<tbody>
							{rows.map((row, index) => (
								<tr key={index}>
									<td>{String(row.name ?? row.code ?? row.id ?? JSON.stringify(row))}</td>
								</tr>
							))}
						</tbody>
					</table>
				</>
			)}
		</Page>
	);
}
