/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { Fixture, PROCESS_LABELS, Result } from './types';

const RESULT_SCHEME = 'certiqs-result';
const FIXTURE_CANDIDATES = [
	'synthetic-fixture.json',
	'.cursor/certiqs-ide/synthetic-fixture.json',
];

let extensionRoot: vscode.Uri | undefined;

export function activate(context: vscode.ExtensionContext): void {
	extensionRoot = context.extensionUri;
	const store = new AssuranceStore();
	const tree = new RecordTreeProvider(store);
	const results = new ResultDocumentProvider(store);

	context.subscriptions.push(
		store,
		tree,
		vscode.window.registerTreeDataProvider('certiqs.assurance.records', tree),
		vscode.workspace.registerTextDocumentContentProvider(RESULT_SCHEME, results),
		vscode.commands.registerCommand('certiqs.assurance.openFixture', () => openFixture(store)),
		vscode.commands.registerCommand('certiqs.assurance.runSynthetic', () => runSynthetic(store, results)),
		vscode.commands.registerCommand('certiqs.assurance.exportResult', () => exportResult(store)),
		vscode.commands.registerCommand('certiqs.assurance.openRecord', (item: RecordItem) => openRecord(item, store, results)),
	);

	void openFixture(store, true);
}

export function deactivate(): void { }

class AssuranceStore extends vscode.Disposable {
	private _fixture: { value: Fixture; uri: vscode.Uri } | undefined;
	private _result: Result | undefined;
	private readonly _onDidChange = new vscode.EventEmitter<void>();
	readonly onDidChange = this._onDidChange.event;

	constructor() {
		super(() => this._onDidChange.dispose());
	}

	get fixture(): { value: Fixture; uri: vscode.Uri } | undefined {
		return this._fixture;
	}

	get result(): Result | undefined {
		return this._result;
	}

	setFixture(value: Fixture, uri: vscode.Uri): void {
		this._fixture = { value, uri };
		this._onDidChange.fire();
	}

	setResult(value: Result): void {
		this._result = value;
		this._onDidChange.fire();
	}
}

class RecordItem extends vscode.TreeItem {
	constructor(
		label: string,
		readonly recordId: string,
		collapsibleState: vscode.TreeItemCollapsibleState,
		description?: string,
	) {
		super(label, collapsibleState);
		this.description = description;
		this.command = { command: 'certiqs.assurance.openRecord', title: 'Open', arguments: [this] };
	}
}

class RecordTreeProvider implements vscode.TreeDataProvider<RecordItem>, vscode.Disposable {
	private readonly _onDidChange = new vscode.EventEmitter<RecordItem | undefined>();
	readonly onDidChangeTreeData = this._onDidChange.event;

	constructor(private readonly store: AssuranceStore) {
		store.onDidChange(() => this._onDidChange.fire(undefined));
	}

	dispose(): void {
		this._onDidChange.dispose();
	}

	getTreeItem(element: RecordItem): vscode.TreeItem {
		return element;
	}

	getChildren(element?: RecordItem): RecordItem[] {
		if (element) {
			return [];
		}
		const loaded = this.store.fixture;
		if (!loaded) {
			return [new RecordItem('No fixture loaded', 'empty', vscode.TreeItemCollapsibleState.None, 'Run certiqs: Open Fixture')];
		}
		const f = loaded.value;
		const items = [
			new RecordItem(f.fixture_id, f.fixture_id, vscode.TreeItemCollapsibleState.None, f.origin),
			new RecordItem(f.procedure.id, f.procedure.id, vscode.TreeItemCollapsibleState.None, f.procedure.version),
			new RecordItem(f.display_observations[0]?.id ?? 'observation', f.display_observations[0]?.id ?? 'observation', vscode.TreeItemCollapsibleState.None, f.display_observations[0]?.label),
			new RecordItem('evidence.fixture', 'evidence.fixture', vscode.TreeItemCollapsibleState.None, f.evidence_availability.fixture),
			new RecordItem('evidence.calibration', 'evidence.calibration', vscode.TreeItemCollapsibleState.None, f.evidence_availability.calibration),
		];
		for (const label of PROCESS_LABELS) {
			items.push(new RecordItem(label, `label:${label}`, vscode.TreeItemCollapsibleState.None, 'category'));
		}
		if (this.store.result) {
			items.push(new RecordItem(this.store.result.runId, this.store.result.runId, vscode.TreeItemCollapsibleState.None, this.store.result.state));
		}
		return items;
	}
}

class ResultDocumentProvider implements vscode.TextDocumentContentProvider {
	private readonly _onDidChange = new vscode.EventEmitter<vscode.Uri>();
	readonly onDidChange = this._onDidChange.event;

	constructor(private readonly store: AssuranceStore) { }

	refresh(uri: vscode.Uri): void {
		this._onDidChange.fire(uri);
	}

	provideTextDocumentContent(uri: vscode.Uri): string {
		const result = this.store.result;
		if (!result || uri.path !== `/${result.runId}`) {
			return JSON.stringify({ type: 'error', code: 'unknown-run', message: 'No result for this identity.' }, null, 2);
		}
		return formatResult(result);
	}
}

function formatResult(result: Result): string {
	return [
		`schemaVersion: ${result.schemaVersion}`,
		`runId: ${result.runId}`,
		`origin: ${result.origin}`,
		`state: ${result.state}`,
		`labels:`,
		...result.labels.map(label => `  - ${label}`),
		`fixture: ${result.fixtureRef.id} (${result.fixtureRef.sourceUri} @ ${result.fixtureRef.revision})`,
		`procedure: ${result.procedureRef.id}`,
		`findings:`,
		...result.findings.map(finding => `  - ${finding.id}: ${finding.summary} [${finding.evidence}]`),
		`limitations:`,
		...result.limitations.map(limitation => `  - ${limitation}`),
	].join('\n');
}

async function openFixture(store: AssuranceStore, silent = false): Promise<void> {
	const located = await locateFixture();
	if (!located) {
		if (!silent) {
			void vscode.window.showErrorMessage('No synthetic-fixture.json found. Add one at the workspace root, or keep the bundled demo fixture in the extension.');
		}
		return;
	}
	try {
		const bytes = await vscode.workspace.fs.readFile(located);
		const parsed = JSON.parse(new TextDecoder().decode(bytes)) as Fixture;
		if (!parsed.fixture_id || parsed.origin !== 'synthetic') {
			throw new Error('Fixture is missing fixture_id or origin=synthetic.');
		}
		store.setFixture(parsed, located);
		if (!silent) {
			await vscode.window.showTextDocument(located, { preview: true });
		}
	} catch (error) {
		if (!silent) {
			void vscode.window.showErrorMessage(`certiqs: ${(error as Error).message}`);
		}
	}
}

async function runSynthetic(store: AssuranceStore, results: ResultDocumentProvider): Promise<void> {
	const denied = denyIfUntrusted('requestSyntheticRun');
	if (denied) {
		void vscode.window.showErrorMessage(denied.message);
		return;
	}
	if (!store.fixture) {
		await openFixture(store);
	}
	const loaded = store.fixture;
	if (!loaded) {
		return;
	}
	const now = new Date().toISOString();
	const runId = `RUN-${now.replace(/[:.]/g, '-')}`;
	const calibration = loaded.value.evidence_availability.calibration;
	const result: Result = {
		schemaVersion: 'certiqs-result/0.1',
		runId,
		fixtureRef: {
			id: loaded.value.fixture_id,
			kind: 'requirement',
			sourceUri: loaded.uri.toString(),
			revision: loaded.value.schema_version,
		},
		procedureRef: {
			id: loaded.value.procedure.id,
			kind: 'procedure',
			sourceUri: loaded.uri.toString(),
			revision: loaded.value.procedure.version,
		},
		state: 'completed',
		origin: 'synthetic',
		labels: PROCESS_LABELS,
		startedAt: now,
		endedAt: now,
		findings: [
			{
				id: loaded.value.display_observations[0]?.id ?? 'DEMO-OBS-001',
				recordRef: {
					id: loaded.value.display_observations[0]?.id ?? 'DEMO-OBS-001',
					kind: 'finding',
					sourceUri: loaded.uri.toString(),
					revision: loaded.value.schema_version,
				},
				summary: loaded.value.display_observations[0]?.value ?? 'Authored placeholder',
				evidence: loaded.value.evidence_availability.fixture === 'available' ? 'present' : 'missing',
			},
		],
		limitations: [
			loaded.value.notice,
			`calibration: ${calibration}`,
		],
	};
	store.setResult(result);
	const uri = vscode.Uri.from({ scheme: RESULT_SCHEME, path: `/${runId}` });
	results.refresh(uri);
	await vscode.window.showTextDocument(uri, { preview: true });
}

async function exportResult(store: AssuranceStore): Promise<void> {
	const denied = denyIfUntrusted('exportRecord');
	if (denied) {
		void vscode.window.showErrorMessage(denied.message);
		return;
	}
	const result = store.result;
	if (!result) {
		void vscode.window.showErrorMessage('No synthetic result to export.');
		return;
	}
	const folder = vscode.workspace.workspaceFolders?.[0];
	const dest = await vscode.window.showSaveDialog({
		defaultUri: folder
			? vscode.Uri.joinPath(folder.uri, `${result.runId}.json`)
			: undefined,
		filters: { JSON: ['json'] },
	});
	if (!dest) {
		return;
	}
	if (folder && !dest.path.startsWith(folder.uri.path)) {
		void vscode.window.showErrorMessage('Export destination must stay inside the workspace.');
		return;
	}
	const payload = {
		...result,
		labels: [...result.labels],
		exportedAt: new Date().toISOString(),
	};
	await vscode.workspace.fs.writeFile(dest, new TextEncoder().encode(JSON.stringify(payload, null, 2)));
	void vscode.window.showInformationMessage(`Exported ${result.runId} with category labels intact.`);
}

async function openRecord(item: RecordItem, store: AssuranceStore, results: ResultDocumentProvider): Promise<void> {
	if (item.recordId.startsWith('RUN-') && store.result) {
		const uri = vscode.Uri.from({ scheme: RESULT_SCHEME, path: `/${store.result.runId}` });
		results.refresh(uri);
		await vscode.window.showTextDocument(uri, { preview: true });
		return;
	}
	if (store.fixture) {
		await vscode.window.showTextDocument(store.fixture.uri, { preview: true });
	}
}

async function locateFixture(): Promise<vscode.Uri | undefined> {
	const folders = vscode.workspace.workspaceFolders ?? [];
	for (const folder of folders) {
		for (const relative of FIXTURE_CANDIDATES) {
			const uri = vscode.Uri.joinPath(folder.uri, ...relative.split('/'));
			try {
				await vscode.workspace.fs.stat(uri);
				return uri;
			} catch {
				// try next
			}
		}
	}
	const found = await vscode.workspace.findFiles('**/synthetic-fixture.json', '**/node_modules/**', 1);
	if (found[0]) {
		return found[0];
	}
	if (extensionRoot) {
		const bundled = vscode.Uri.joinPath(extensionRoot, 'fixtures', 'synthetic-fixture.json');
		try {
			await vscode.workspace.fs.stat(bundled);
			return bundled;
		} catch {
			// none
		}
	}
	return undefined;
}

function denyIfUntrusted(type: 'requestSyntheticRun' | 'exportRecord'): { code: string; message: string; retryable: false } | undefined {
	if (vscode.workspace.isTrusted) {
		return undefined;
	}
	return {
		code: 'untrusted-workspace',
		message: `${type} is denied in an untrusted workspace.`,
		retryable: false,
	};
}
