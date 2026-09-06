/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { HqHub, HqMessenger } from './hqHub';
import { HostToWebview, WebviewToHost } from './protocol';
import { renderHqHtml } from './webviewHtml';

export const HQ_VIEW_ID = 'certiqs.hq.panel';

export class HqViewProvider implements vscode.WebviewViewProvider {
	private view: vscode.WebviewView | undefined;
	private attached: vscode.Disposable | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly hub: HqHub,
	) { }

	resolveWebviewView(webviewView: vscode.WebviewView): void {
		this.view = webviewView;
		this.attached?.dispose();
		webviewView.webview.options = {
			enableScripts: true,
			localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
		};
		webviewView.webview.html = renderHqHtml(webviewView.webview, this.extensionUri, 'hq');
		this.attached = this.hub.attach(this.messenger());
		webviewView.webview.onDidReceiveMessage((message: WebviewToHost) => {
			void this.hub.handle(message);
		});
		webviewView.onDidDispose(() => {
			this.attached?.dispose();
			this.attached = undefined;
			this.view = undefined;
		});
	}

	async refresh(): Promise<void> {
		await this.hub.refresh();
	}

	private messenger(): HqMessenger {
		return {
			post: (message: HostToWebview) => this.view?.webview.postMessage(message),
		};
	}
}
