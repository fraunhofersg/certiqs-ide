/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export const SEARCH_STATE_KEY = 'certiqs.qdb.searchTree';
export const SELECTED_SYSTEM_KEY = 'certiqs.qdb.selectedSystemId';
export const WORKSPACE_USER_KEY = 'certiqs.qdb.workspaceUserId';

export type QdbSurface =
	| 'sidebar'
	| 'inspector'
	| 'hub'
	| 'systems'
	| 'wizard'
	| 'system'
	| 'applicability'
	| 'search'
	| 'vulnerabilities'
	| 'eas'
	| 'countermeasures'
	| 'documents';

export type ApiState = 'stopped' | 'starting' | 'ready' | 'error';

export type QdbState = {
	api: ApiState;
	apiError?: string;
	pythonPath: string;
	port: number;
	userId: string;
	isAdmin: boolean;
	selectedSystemId?: number;
	notice: string;
};

export type ApiRequest = {
	method: string;
	path: string;
	query?: Record<string, string | number | boolean | Array<string | number | boolean>>;
	body?: unknown;
	binary?: boolean;
};

export type ApiJsonResult = {
	ok: boolean;
	status: number;
	json: unknown;
	headers: Record<string, string>;
};

export type ApiBinaryResult = {
	ok: boolean;
	status: number;
	base64: string;
	contentType: string;
	fileName?: string;
	warnings?: string;
	json?: unknown;
};

export type RpcMethod =
	| 'api'
	| 'exportZip'
	| 'saveSearchTree'
	| 'loadSearchTree'
	| 'setSelectedSystem'
	| 'openExternal'
	| 'pickPdf';

export type HostToWebview =
	| { type: 'state'; payload: QdbState }
	| { type: 'rpcResult'; id: string; result: unknown }
	| { type: 'rpcError'; id: string; error: string };

export type WebviewToHost =
	| { type: 'ready' }
	| { type: 'refresh' }
	| { type: 'startApi' }
	| { type: 'stopApi' }
	| { type: 'showLog' }
	| { type: 'openPage'; surface: QdbSurface; systemId?: number }
	| { type: 'rpc'; id: string; method: RpcMethod; params?: Record<string, unknown> };
