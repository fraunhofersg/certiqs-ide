/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import type { BootstrapSnapshot, RunStatus, StreamMessage } from './apiTypes';

export const PROCESS_LABELS = [
	'synthetic',
	'not a measurement',
	'not a security or conformity statement',
] as const;

export type ApiState = 'stopped' | 'starting' | 'ready' | 'error';
export type RunLifecycle = 'idle' | 'starting' | 'stopping';

export type { RunStatus };

export type SimState = {
	api: ApiState;
	apiError?: string;
	pythonPath: string;
	port: number;
	configs: string[];
	configName: string;
	shotsPerWindow: number;
	lifecycle: RunLifecycle;
	status?: RunStatus;
	labels: readonly string[];
	notice: string;
	iconBase?: string;
};

export type RpcMethod =
	| 'getMeta'
	| 'getConfigs'
	| 'getMetricsCatalog'
	| 'getForensicsConfig'
	| 'getOptimizationConfig'
	| 'getStatus'
	| 'getHistory'
	| 'setParams'
	| 'getConfigFiles'
	| 'getComponentInventory'
	| 'getComponentTaxonomy'
	| 'getComponentTopology'
	| 'getSimTerminalExamples'
	| 'postSimTerminalPrompt'
	| 'getBootstrap';

export type HostToWebview =
	| { type: 'state'; payload: SimState }
	| { type: 'bootstrap'; payload: BootstrapSnapshot }
	| { type: 'stream'; frames: StreamMessage[] }
	| { type: 'rpcResult'; id: string; result: unknown }
	| { type: 'rpcError'; id: string; error: string };

export type WebviewToHost =
	| { type: 'ready' }
	| { type: 'refresh' }
	| { type: 'startApi' }
	| { type: 'stopApi' }
	| { type: 'startRun' }
	| { type: 'stopRun' }
	| { type: 'setConfig'; configName: string }
	| { type: 'setShots'; shotsPerWindow: number }
	| { type: 'openWelcome' }
	| { type: 'openOverview' }
	| { type: 'openDashboard' }
	| { type: 'openSystem' }
	| { type: 'focusRunControl' }
	| { type: 'showLog' }
	| { type: 'showMonitor' }
	| { type: 'showForensics' }
	| { type: 'showDebug' }
	| { type: 'showPrompt' }
	| { type: 'rpc'; id: string; method: RpcMethod; params?: Record<string, unknown> };
