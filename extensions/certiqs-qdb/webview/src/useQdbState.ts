import { useEffect, useState } from 'react';
import type { QdbState } from '../../src/protocol';
import { onHostMessage, post } from './vscodeApi';

const INITIAL: QdbState = {
	api: 'stopped',
	pythonPath: 'python3',
	port: 8012,
	userId: '',
	isAdmin: false,
	notice: '',
};

export function useQdbState(): QdbState {
	const [state, setState] = useState<QdbState>(INITIAL);
	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'state') {
				setState(message.payload);
			}
		});
		post({ type: 'ready' });
		return dispose;
	}, []);
	return state;
}

export function surfaceSystemId(): number | undefined {
	const raw = document.body.dataset.systemId;
	const parsed = raw ? Number(raw) : NaN;
	return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

export function surfaceIsAdmin(): boolean {
	return document.body.dataset.admin === 'true';
}
