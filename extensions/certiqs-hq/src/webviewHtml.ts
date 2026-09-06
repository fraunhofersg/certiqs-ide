/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { HqSurface } from './protocol';

const TITLES: Record<HqSurface, string> = {
	hq: 'HQ',
	settings: 'certiqs Settings',
	lens: 'Context Lens',
	chat: 'Chat Session',
	brainstorm: 'Brainstorming',
	architect: 'Architect',
};

export function renderHqHtml(
	webview: vscode.Webview,
	extensionUri: vscode.Uri,
	surface: HqSurface,
	sessionId?: string,
): string {
	const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'webview.js'));
	const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'webview.css'));
	const nonce = getNonce();
	const csp = [
		`default-src 'none'`,
		`img-src ${webview.cspSource} https: http: data: blob:`,
		`font-src ${webview.cspSource} data:`,
		`style-src ${webview.cspSource} 'unsafe-inline'`,
		`script-src 'nonce-${nonce}' ${webview.cspSource}`,
	].join('; ');
	const title = TITLES[surface];
	const sessionAttr = sessionId ? ` data-session-id="${escapeHtml(sessionId)}"` : '';
	return `<!DOCTYPE html>
<html lang="en" class="dark" data-theme="dark">
<head>
	<meta charset="UTF-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<meta http-equiv="Content-Security-Policy" content="${csp}" />
	<link rel="stylesheet" href="${styleUri}" />
	<title>${title}</title>
</head>
<body class="bg-background text-foreground" data-surface="${surface}"${sessionAttr}>
	<div id="root">Loading ${title}…</div>
	<script nonce="${nonce}">globalThis.process = globalThis.process || { env: { NODE_ENV: 'production' } };</script>
	<script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
}

function escapeHtml(value: string): string {
	return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!));
}

function getNonce(): string {
	const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
	let nonce = '';
	for (let i = 0; i < 32; i++) {
		nonce += chars.charAt(Math.floor(Math.random() * chars.length));
	}
	return nonce;
}
