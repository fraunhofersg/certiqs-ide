/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

export type SimSurface = 'sidebar' | 'welcome' | 'overview' | 'dashboard' | 'system';

export function renderSimHtml(webview: vscode.Webview, extensionUri: vscode.Uri, surface: SimSurface): string {
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
	const titles: Record<SimSurface, string> = {
		sidebar: 'Run Control',
		welcome: 'certiqs Sim',
		overview: 'certiqs Sim',
		dashboard: 'Sim Dashboard',
		system: 'Sim System',
	};
	const title = titles[surface];
	const loading = `Loading ${title}…`;
	return `<!DOCTYPE html>
<html lang="en" class="dark" data-theme="dark">
<head>
	<meta charset="UTF-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<meta http-equiv="Content-Security-Policy" content="${csp}" />
	<link rel="stylesheet" href="${styleUri}" />
	<title>${title}</title>
</head>
<body class="bg-background text-foreground" data-surface="${surface}">
	<div id="root">${loading}</div>
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
