/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { HostToWebview, QdbSurface, WebviewToHost } from './protocol';
import { QdbMessenger, QdbSession } from './qdbSession';
import { renderQdbHtml } from './webviewHtml';

export const QDB_VIEW_ID = 'certiqs.qdb.panel';
export const QDB_INSPECTOR_ID = 'certiqs.qdb.inspector';

export class QdbViewProvider implements vscode.WebviewViewProvider {
	private view: vscode.WebviewView | undefined;
	private attached: vscode.Disposable | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly session: QdbSession,
		private readonly surface: QdbSurface,
		private readonly onVisible: () => void = () => { },
	) { }

	resolveWebviewView(webviewView: vscode.WebviewView): void {
		this.view = webviewView;
		webviewView.webview.options = {
			enableScripts: true,
			localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
		};
		webviewView.webview.html = renderQdbHtml(webviewView.webview, this.extensionUri, this.surface, {
			isAdmin: this.session.isAdmin,
			systemId: this.session.selectedSystemId,
		});
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

	private messenger(): QdbMessenger {
		return {
			post: (message: HostToWebview) => this.view?.webview.postMessage(message),
		};
	}
}
