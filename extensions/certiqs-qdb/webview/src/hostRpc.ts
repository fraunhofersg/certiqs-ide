import type { ApiJsonResult, QdbSurface, RpcMethod } from '../../src/protocol';
import { onHostMessage, post } from './vscodeApi';

export function rpc<T>(method: RpcMethod, params?: Record<string, unknown>): Promise<T> {
	const id = `${method}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
	return new Promise((resolve, reject) => {
		const dispose = onHostMessage(message => {
			if (message.type === 'rpcResult' && message.id === id) {
				dispose();
				resolve(message.result as T);
			}
			if (message.type === 'rpcError' && message.id === id) {
				dispose();
				reject(new Error(message.error));
			}
		});
		post({ type: 'rpc', id, method, params });
	});
}

export async function api<T>(
	method: string,
	path: string,
	init?: {
		query?: Record<string, string | number | boolean | Array<string | number | boolean>>;
		body?: unknown;
	},
): Promise<T> {
	const result = await rpc<ApiJsonResult>('api', {
		method,
		path,
		query: init?.query,
		body: init?.body,
	});
	if (!result.ok) {
		throw new Error(formatApiError(result.status, result.json));
	}
	return result.json as T;
}

export function openPage(surface: QdbSurface, systemId?: number): void {
	post({ type: 'openPage', surface, systemId });
}

function formatApiError(status: number, json: unknown): string {
	if (json && typeof json === 'object') {
		const record = json as { detail?: unknown; error?: unknown };
		if (typeof record.detail === 'string') {
			return record.detail;
		}
		if (typeof record.error === 'string') {
			return record.error;
		}
		if (record.detail !== undefined) {
			return JSON.stringify(record.detail);
		}
	}
	return `QDB API ${status}`;
}
