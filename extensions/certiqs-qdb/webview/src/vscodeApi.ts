import type { HostToWebview, WebviewToHost } from '../../src/protocol';

type VsCodeApi = {
	postMessage(message: WebviewToHost): void;
	getState(): unknown;
	setState(state: unknown): void;
};

declare function acquireVsCodeApi(): VsCodeApi;

export const vscodeApi = acquireVsCodeApi();

export function post(message: WebviewToHost): void {
	vscodeApi.postMessage(message);
}

export function onHostMessage(handler: (message: HostToWebview) => void): () => void {
	const listener = (event: MessageEvent<HostToWebview>) => {
		if (event.data && typeof event.data === 'object' && 'type' in event.data) {
			handler(event.data);
		}
	};
	window.addEventListener('message', listener);
	return () => window.removeEventListener('message', listener);
}
