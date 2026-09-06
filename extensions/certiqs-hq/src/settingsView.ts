/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { loadHqSettings } from './hqSettings';
import { HostToWebview, WebviewToHost } from './protocol';
import { loadSettingsCatalog, runSettingsCommand } from './settingsRegistry';
import { SettingsCatalog, SettingsSourceState } from './settingsContract';
import { renderHqHtml } from './webviewHtml';

export const SETTINGS_VIEW_ID = 'certiqs.hq.settings';

export class SettingsViewProvider implements vscode.WebviewViewProvider {
	private view: vscode.WebviewView | undefined;
	private local: SettingsSourceState | undefined;

	constructor(private readonly extensionUri: vscode.Uri) { }

	resolveWebviewView(webviewView: vscode.WebviewView): void {
		this.view = webviewView;
		webviewView.webview.options = {
			enableScripts: true,
			localResourceRoots: [this.extensionUri, vscode.Uri.joinPath(this.extensionUri, 'media')],
		};
		webviewView.webview.html = renderHqHtml(webviewView.webview, this.extensionUri, 'settings');
		webviewView.webview.onDidReceiveMessage((message: WebviewToHost) => {
			void this.onMessage(message);
		});
	}

	async refresh(): Promise<void> {
		await this.postCatalog();
	}

	private async onMessage(message: WebviewToHost): Promise<void> {
		switch (message.type) {
			case 'readySettings':
			case 'refresh':
				await this.postCatalog();
				return;
			case 'saveSettings':
				await this.invoke(message.sourceId, {
					type: 'set',
					values: message.values,
					secrets: message.secrets,
					clearSecrets: message.clearSecrets,
				});
				await this.postCatalog();
				return;
			case 'runSettingsAction':
				if (message.actionId === 'save') {
					return;
				}
				if (message.values || message.secrets) {
					await this.invoke(message.sourceId, {
						type: 'set',
						values: message.values ?? {},
						secrets: message.secrets,
					});
				}
				await this.invoke(message.sourceId, { type: 'action', id: message.actionId });
				await this.postCatalog();
				return;
		}
	}

	private async invoke(sourceId: string, command: Parameters<typeof runSettingsCommand>[1]): Promise<void> {
		try {
			const local = await this.ensureLocal();
			await runSettingsCommand(sourceId, command, local, this.extensionUri);
		} catch (error) {
			void vscode.window.showErrorMessage(`certiqs settings: ${(error as Error).message}`);
		}
	}

	private async postCatalog(): Promise<void> {
		if (!this.view) {
			return;
		}
		const local = await this.ensureLocal();
		const catalog = await this.resolvePreviews(await loadSettingsCatalog(local));
		const message: HostToWebview = { type: 'settings', payload: catalog };
		await this.view.webview.postMessage(message);
	}

	private async resolvePreviews(catalog: SettingsCatalog): Promise<SettingsCatalog> {
		const sources = [];
		for (const source of catalog.sources) {
			const sections = [];
			for (const section of source.sections) {
				const fields = [];
				for (const field of section.fields) {
					if (!field.options?.length) {
						fields.push(field);
						continue;
					}
					const options = [];
					for (const option of field.options) {
						options.push({
							...option,
							preview: option.preview ? await this.toPreviewDataUri(option.preview) : undefined,
						});
					}
					fields.push({ ...field, options });
				}
				sections.push({ ...section, fields });
			}
			sources.push({ ...source, sections });
		}
		return { sources };
	}

	private async toPreviewDataUri(relative: string): Promise<string | undefined> {
		const uri = vscode.Uri.joinPath(this.extensionUri, ...relative.split('/').filter(Boolean));
		try {
			const bytes = await vscode.workspace.fs.readFile(uri);
			const mime = relative.endsWith('.svg') ? 'image/svg+xml' : 'image/png';
			return `data:${mime};base64,${encodeBase64(bytes)}`;
		} catch {
			return this.view?.webview.asWebviewUri(uri).toString();
		}
	}

	private async ensureLocal(): Promise<SettingsSourceState> {
		this.local = await loadHqSettings(this.extensionUri);
		return this.local;
	}
}

function encodeBase64(bytes: Uint8Array): string {
	let binary = '';
	const chunk = 0x8000;
	for (let i = 0; i < bytes.length; i += chunk) {
		binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
	}
	return btoa(binary);
}
