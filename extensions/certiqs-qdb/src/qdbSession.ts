/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { randomUUID } from 'crypto';
import * as vscode from 'vscode';
import { signInternalToken } from './internalAuth';
import {
	ApiRequest,
	HostToWebview,
	QdbState,
	QdbSurface,
	RpcMethod,
	SEARCH_STATE_KEY,
	SELECTED_SYSTEM_KEY,
	WebviewToHost,
	WORKSPACE_USER_KEY,
} from './protocol';
import { rewriteInternalPath, rewriteLookupUrls } from './rewritePaths';
import { ServiceRuntime } from './serviceRuntime';

export type QdbMessenger = {
	post(message: HostToWebview): Thenable<boolean> | undefined;
};

const PAGE_COMMANDS: Record<QdbSurface, string | undefined> = {
	sidebar: 'certiqs.qdb.panel.focus',
	inspector: 'certiqs.qdb.inspector.focus',
	hub: 'certiqs.qdb.openHub',
	systems: 'certiqs.qdb.openSystems',
	wizard: 'certiqs.qdb.openWizard',
	system: 'certiqs.qdb.openSystem',
	applicability: 'certiqs.qdb.openApplicability',
	search: 'certiqs.qdb.openSearch',
	vulnerabilities: 'certiqs.qdb.openVulnerabilities',
	eas: 'certiqs.qdb.openEAs',
	countermeasures: 'certiqs.qdb.openCountermeasures',
	documents: 'certiqs.qdb.openDocuments',
};

export class QdbSession implements vscode.Disposable {
	private readonly views = new Set<QdbMessenger>();
	apiHint: QdbState['api'] | undefined;
	selectedSystemId: number | undefined;

	constructor(
		private readonly context: vscode.ExtensionContext,
		private readonly runtime: ServiceRuntime,
	) {
		const stored = context.workspaceState.get<number>(SELECTED_SYSTEM_KEY);
		if (typeof stored === 'number') {
			this.selectedSystemId = stored;
		}
	}

	attach(view: QdbMessenger): vscode.Disposable {
		this.views.add(view);
		return new vscode.Disposable(() => this.views.delete(view));
	}

	get userId(): string {
		const configured = vscode.workspace.getConfiguration('certiqs.qdb').get<string>('userId', '').trim();
		if (configured) {
			return configured;
		}
		const existing = this.context.globalState.get<string>(WORKSPACE_USER_KEY);
		if (existing) {
			return existing;
		}
		const generated = randomUUID();
		void this.context.globalState.update(WORKSPACE_USER_KEY, generated);
		return generated;
	}

	get isAdmin(): boolean {
		return vscode.workspace.getConfiguration('certiqs.qdb').get<boolean>('isAdmin', false);
	}

	async handle(message: WebviewToHost): Promise<void> {
		switch (message.type) {
			case 'ready':
			case 'refresh':
				if (vscode.workspace.getConfiguration('certiqs.qdb').get('autoStartApi', true)) {
					await this.startApi();
				} else {
					await this.broadcastState();
				}
				return;
			case 'startApi':
				await this.startApi();
				return;
			case 'stopApi':
				await this.runtime.stop();
				await this.broadcastState();
				return;
			case 'showLog':
				this.runtime.showOutput();
				return;
			case 'openPage':
				await this.openPage(message.surface, message.systemId);
				return;
			case 'rpc':
				await this.rpc(message.id, message.method, message.params ?? {});
				return;
		}
	}

	async startApi(): Promise<void> {
		this.apiHint = 'starting';
		await this.broadcastState();
		try {
			await this.runtime.ensureStarted();
			this.apiHint = undefined;
		} catch (error) {
			this.apiHint = 'error';
			void vscode.window.showErrorMessage(`certiqs QDB: ${(error as Error).message}`);
		}
		await this.broadcastState();
	}

	async openPage(surface: QdbSurface, systemId?: number): Promise<void> {
		if (typeof systemId === 'number') {
			this.selectedSystemId = systemId;
			await this.context.workspaceState.update(SELECTED_SYSTEM_KEY, systemId);
			await this.broadcastState();
		}
		const command = PAGE_COMMANDS[surface];
		if (command) {
			if (surface === 'system' && typeof systemId === 'number') {
				await vscode.commands.executeCommand(command, systemId);
			} else {
				await vscode.commands.executeCommand(command);
			}
		}
	}

	async broadcastState(): Promise<void> {
		const payload = await this.state();
		for (const view of this.views) {
			void view.post({ type: 'state', payload });
		}
	}

	async state(): Promise<QdbState> {
		const ready = await this.runtime.health();
		let api: QdbState['api'] = 'stopped';
		let apiError: string | undefined;
		if (this.apiHint === 'starting') {
			api = 'starting';
		} else if (this.apiHint === 'error') {
			api = 'error';
			apiError = (await this.runtime.snapshot()).reason;
		} else if (ready) {
			api = 'ready';
		}
		return {
			api,
			apiError,
			pythonPath: this.runtime.pythonPath,
			port: this.runtime.port,
			userId: this.userId,
			isAdmin: this.isAdmin,
			selectedSystemId: this.selectedSystemId,
			notice: 'QKD compliance workbench. Catalogue engines run in the local FastAPI service. Not a measurement.',
		};
	}

	dispose(): void {
		this.views.clear();
	}

	private async rpc(id: string, method: RpcMethod, params: Record<string, unknown>): Promise<void> {
		try {
			const result = await this.dispatch(method, params);
			this.postAll({ type: 'rpcResult', id, result });
		} catch (error) {
			this.postAll({ type: 'rpcError', id, error: (error as Error).message });
		}
	}

	private postAll(message: HostToWebview): void {
		for (const view of this.views) {
			void view.post(message);
		}
	}

	private async dispatch(method: RpcMethod, params: Record<string, unknown>): Promise<unknown> {
		switch (method) {
			case 'api':
				return this.proxy(params as ApiRequest);
			case 'exportZip':
				return this.exportZip(Number(params.systemId), params.paramValues);
			case 'saveSearchTree':
				await this.context.workspaceState.update(SEARCH_STATE_KEY, params.tree ?? null);
				return { ok: true };
			case 'loadSearchTree':
				return { tree: this.context.workspaceState.get(SEARCH_STATE_KEY) ?? null };
			case 'setSelectedSystem': {
				const systemId = Number(params.systemId);
				this.selectedSystemId = Number.isFinite(systemId) ? systemId : undefined;
				await this.context.workspaceState.update(SELECTED_SYSTEM_KEY, this.selectedSystemId);
				await this.broadcastState();
				return { selectedSystemId: this.selectedSystemId };
			}
			case 'openExternal': {
				const url = String(params.url ?? '');
				if (url) {
					await vscode.env.openExternal(vscode.Uri.parse(url));
				}
				return { ok: true };
			}
			case 'pickPdf':
				return this.pickPdf();
		}
	}

	private async proxy(request: ApiRequest): Promise<unknown> {
		await this.runtime.ensureStarted();
		const env = await this.runtime.loadEnv();
		const path = rewriteInternalPath(request.path);
		const url = new URL(path, this.runtime.origin);
		for (const [key, value] of Object.entries(request.query ?? {})) {
			if (Array.isArray(value)) {
				for (const item of value) {
					url.searchParams.append(key, String(item));
				}
			} else if (value !== undefined && value !== null && value !== '') {
				url.searchParams.set(key, String(value));
			}
		}
		const token = signInternalToken({
			userId: this.userId,
			isAdmin: this.isAdmin,
			secret: env.internalAuthSecret,
			ttlSeconds: env.internalAuthTtlSeconds,
		});
		const headers: Record<string, string> = {
			Authorization: `Internal ${token}`,
		};
		let body: string | undefined;
		if (request.body !== undefined && request.method !== 'GET') {
			headers['Content-Type'] = 'application/json';
			body = JSON.stringify(request.body);
		}
		const res = await fetch(url, { method: request.method, headers, body });
		const responseHeaders: Record<string, string> = {};
		res.headers.forEach((value, key) => {
			responseHeaders[key.toLowerCase()] = value;
		});
		if (request.binary) {
			if (!res.ok) {
				const text = await res.text();
				let json: unknown = text;
				try {
					json = JSON.parse(text);
				} catch {
					json = { error: text };
				}
				return { ok: false, status: res.status, base64: '', contentType: 'application/json', json, headers: responseHeaders };
			}
			const buffer = Buffer.from(await res.arrayBuffer());
			return {
				ok: true,
				status: res.status,
				base64: buffer.toString('base64'),
				contentType: res.headers.get('content-type') ?? 'application/zip',
				fileName: parseFileName(res.headers.get('content-disposition')),
				warnings: res.headers.get('x-export-warnings') ?? undefined,
				headers: responseHeaders,
			};
		}
		const text = await res.text();
		let json: unknown = text;
		if (text) {
			try {
				json = JSON.parse(text);
			} catch {
				json = { error: text };
			}
		} else {
			json = null;
		}
		if (path.includes('/search/fields')) {
			json = rewriteLookupUrls(json);
		}
		return { ok: res.ok, status: res.status, json, headers: responseHeaders };
	}

	private async exportZip(systemId: number, paramValues: unknown): Promise<unknown> {
		const result = await this.proxy({
			method: 'POST',
			path: `/internal/export/${systemId}`,
			body: { paramValues: paramValues ?? {} },
			binary: true,
		}) as { ok: boolean; status: number; base64: string; fileName?: string; warnings?: string; json?: unknown };
		if (!result.ok) {
			throw new Error(formatProxyError(result.status, result.json));
		}
		const defaultName = result.fileName || `qkd-system-${systemId}.zip`;
		const uri = await vscode.window.showSaveDialog({
			defaultUri: vscode.Uri.file(defaultName),
			filters: { Zip: ['zip'] },
		});
		if (!uri) {
			return { cancelled: true };
		}
		await vscode.workspace.fs.writeFile(uri, Buffer.from(result.base64, 'base64'));
		if (result.warnings) {
			void vscode.window.showWarningMessage(`QDB export warnings: ${result.warnings}`);
		}
		return { saved: uri.fsPath, warnings: result.warnings };
	}

	private async pickPdf(): Promise<{ label?: string; blobUrl?: string; cancelled?: boolean }> {
		const picked = await vscode.window.showOpenDialog({
			canSelectMany: false,
			filters: { PDF: ['pdf'] },
		});
		if (!picked?.[0]) {
			return { cancelled: true };
		}
		const dest = vscode.Uri.joinPath(this.context.globalStorageUri, 'documents', picked[0].path.split('/').pop() ?? 'source.pdf');
		await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(this.context.globalStorageUri, 'documents'));
		await vscode.workspace.fs.copy(picked[0], dest, { overwrite: true });
		return { label: dest.path.split('/').pop(), blobUrl: dest.toString() };
	}
}

function parseFileName(header: string | null): string | undefined {
	if (!header) {
		return undefined;
	}
	const match = /filename="?([^"]+)"?/i.exec(header);
	return match?.[1];
}

function formatProxyError(status: number, json: unknown): string {
	if (json && typeof json === 'object' && 'detail' in json) {
		const detail = (json as { detail: unknown }).detail;
		return typeof detail === 'string' ? detail : JSON.stringify(detail);
	}
	return `QDB API ${status}`;
}
