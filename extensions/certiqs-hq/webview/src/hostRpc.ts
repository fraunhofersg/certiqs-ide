import type { RpcMethod } from '../../src/protocol';
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
