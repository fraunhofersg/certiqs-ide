/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { HostToWebview, WebviewToHost } from './protocol';
import { SimMessenger, SimSession } from './simSession';
import { renderSimHtml } from './webviewHtml';

export const SIM_VIEW_ID = 'certiqs.sim.panel';

export class SimViewProvider implements vscode.WebviewViewProvider {
	private view: vscode.WebviewView | undefined;
	private attached: vscode.Disposable | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly session: SimSession,
		private readonly onVisible: () => void = () => { },
	) { }

	resolveWebviewView(webviewView: vscode.WebviewView): void {
		this.view = webviewView;
		webviewView.webview.options = {
			enableScripts: true,
			localResourceRoots: [
				vscode.Uri.joinPath(this.extensionUri, 'media'),
				vscode.Uri.joinPath(this.extensionUri, 'icons'),
			],
		};
		webviewView.webview.html = renderSimHtml(webviewView.webview, this.extensionUri, 'sidebar');
		this.attached = this.session.attach(this.messenger());
		webviewView.webview.onDidReceiveMessage((message: WebviewToHost) => {
			void this.session.handle(message);
		});
		webviewView.onDidChangeVisibility(() => {
			if (webviewView.visible) {
				this.onVisible();
			}
		});
		webviewView.onDidDispose(() => {
			this.attached?.dispose();
			this.attached = undefined;
			this.view = undefined;
		});
		this.onVisible();
	}

	async refresh(): Promise<void> {
		await this.session.broadcastState();
	}

	private messenger(): SimMessenger {
		return {
			post: (message: HostToWebview) => this.view?.webview.postMessage(message),
		};
	}
}
