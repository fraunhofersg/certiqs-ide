/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { QdbSurface } from './protocol';

const TITLES: Record<QdbSurface, string> = {
	sidebar: 'QDB Explorer',
	inspector: 'QDB Inspector',
	hub: 'certiqs QDB',
	systems: 'QDB Systems',
	wizard: 'New QDB System',
	system: 'QDB System',
	applicability: 'QDB Applicability',
	search: 'QDB Search',
	vulnerabilities: 'QDB Attacks',
	eas: 'QDB Evaluation Activities',
	countermeasures: 'QDB Countermeasures',
	documents: 'QDB Document Sources',
};

export function renderQdbHtml(
	webview: vscode.Webview,
	extensionUri: vscode.Uri,
	surface: QdbSurface,
	options?: { systemId?: number; isAdmin?: boolean },
): string {
	const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'webview.js'));
	const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'webview.css'));
	const nonce = getNonce();
	const csp = [
		`default-src 'none'`,
		`img-src ${webview.cspSource} https: data:`,
		`font-src ${webview.cspSource} data:`,
		`style-src ${webview.cspSource} 'unsafe-inline'`,
		`script-src 'nonce-${nonce}' ${webview.cspSource}`,
	].join('; ');
	const title = TITLES[surface];
	const systemId = options?.systemId ? String(options.systemId) : '';
	const isAdmin = options?.isAdmin ? 'true' : 'false';
	return `<!DOCTYPE html>
<html lang="en" class="dark" data-theme="dark">
<head>
	<meta charset="UTF-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<meta http-equiv="Content-Security-Policy" content="${csp}" />
	<link rel="stylesheet" href="${styleUri}" />
	<title>${title}</title>
</head>
<body class="bg-background text-foreground" data-surface="${surface}" data-system-id="${systemId}" data-admin="${isAdmin}">
	<div id="root">Loading ${title}…</div>
	<script nonce="${nonce}">globalThis.process = globalThis.process || { env: { NODE_ENV: 'production' } };</script>
	<script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
}

function getNonce(): string {
	const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
	let nonce = '';
	for (let i = 0; i < 32; i++) {
		nonce += chars.charAt(Math.floor(Math.random() * chars.length));
	}
	return nonce;
}
