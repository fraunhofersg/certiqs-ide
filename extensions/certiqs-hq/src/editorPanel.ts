/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { HqHub, HqMessenger } from './hqHub';
import type { SessionFile } from './knowledgeTypes';
import { HostToWebview, HqSurface, WebviewToHost } from './protocol';
import { renderHqHtml } from './webviewHtml';

export class HqEditorPanel implements vscode.Disposable {
	private panel: vscode.WebviewPanel | undefined;
	private attached: vscode.Disposable | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly hub: HqHub,
		private readonly viewType: string,
		private readonly title: string,
		private readonly surface: HqSurface,
		private readonly sessionId?: string,
		private readonly onDispose?: () => void,
	) { }

	show(): void {
		if (this.panel) {
			this.panel.reveal(vscode.ViewColumn.One, false);
			void this.hub.refresh();
			return;
		}
		this.panel = vscode.window.createWebviewPanel(
			this.viewType,
			this.title,
			{ viewColumn: vscode.ViewColumn.One, preserveFocus: false },
			{
				enableScripts: true,
				enableFindWidget: true,
				retainContextWhenHidden: true,
				localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
			},
		);
		this.panel.webview.html = renderHqHtml(this.panel.webview, this.extensionUri, this.surface, this.sessionId);
		this.attached = this.hub.attach(this.messenger());
		this.panel.webview.onDidReceiveMessage((message: WebviewToHost) => {
			void this.hub.handle(message);
		});
		this.panel.onDidChangeViewState(event => {
			if (event.webviewPanel.active && this.sessionId) {
				this.hub.store.setActiveSession(this.sessionId);
			}
		});
		this.panel.onDidDispose(() => {
			this.attached?.dispose();
			this.attached = undefined;
			this.panel = undefined;
			this.onDispose?.();
		});
		void this.hub.refresh();
	}

	dispose(): void {
		this.attached?.dispose();
		this.panel?.dispose();
	}

	private messenger(): HqMessenger {
		return {
			post: (message: HostToWebview) => this.panel?.webview.postMessage(message),
		};
	}
}

export class HqPages implements vscode.Disposable {
	private lens: HqEditorPanel | undefined;
	private readonly sessions = new Map<string, HqEditorPanel>();

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly hub: HqHub,
	) { }

	openLens(): void {
		this.lens ??= new HqEditorPanel(this.extensionUri, this.hub, 'certiqs.hq.lens', 'Context Lens', 'lens');
		this.lens.show();
	}

	openSession(session: SessionFile): void {
		const existing = this.sessions.get(session.id);
		if (existing) {
			existing.show();
			return;
		}
		const surface = session.kind === 'brainstorm' ? 'brainstorm' : session.kind === 'architect' ? 'architect' : 'chat';
		const panel = new HqEditorPanel(
			this.extensionUri,
			this.hub,
			`certiqs.hq.session.${session.kind}`,
			session.title,
			surface,
			session.id,
			() => this.sessions.delete(session.id),
		);
		this.sessions.set(session.id, panel);
		panel.show();
	}

	dispose(): void {
		this.lens?.dispose();
		for (const panel of this.sessions.values()) {
			panel.dispose();
		}
		this.sessions.clear();
	}
}
