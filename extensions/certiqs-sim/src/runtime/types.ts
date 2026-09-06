/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export type RuntimeMode = 'local' | 'docker';

export type RuntimeState = 'stopped' | 'starting' | 'ready' | 'degraded' | 'failed';

export type RuntimeSnapshot = {
	id: string;
	title: string;
	mode: RuntimeMode;
	state: RuntimeState;
	endpoint?: string;
	reason?: string;
	docker?: {
		available: boolean;
		image?: string;
		containerName?: string;
		containerId?: string;
		status?: string;
	};
};

export type RuntimeCommand =
	| { type: 'describe' }
	| { type: 'status' }
	| { type: 'start' }
	| { type: 'stop' }
	| { type: 'restart' }
	| { type: 'logs' }
	| { type: 'rebuild' };
