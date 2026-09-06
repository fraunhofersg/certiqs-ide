/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import type { KnowledgeSnapshot, SessionKind } from './knowledgeTypes';
import type { RuntimeAction, RuntimeSnapshot } from './runtimeContract';
import type { SettingsCatalog } from './settingsContract';

export const PROCESS_LABELS = [
	'synthetic',
	'not a measurement',
	'not a security or conformity statement',
] as const;

export type HqSkill = {
	slug: string;
	path: string;
};

export type HqState = {
	fixtureLoaded: boolean;
	fixtureId?: string;
	resultId?: string;
	skills: HqSkill[];
	mcpConfigured: boolean;
	labels: readonly string[];
	notice: string;
	knowledge?: KnowledgeSnapshot;
};

export type HqSurface = 'hq' | 'settings' | 'lens' | 'chat' | 'brainstorm' | 'architect';

export type RpcMethod =
	| 'getKnowledge'
	| 'setWikiStrategy'
	| 'addWikiFile'
	| 'removeWikiFile'
	| 'toggleLoomHidden'
	| 'removeLoomEntry'
	| 'initializeKnowledge'
	| 'reviewerAction'
	| 'getSession'
	| 'createSession'
	| 'openSession'
	| 'archiveSession'
	| 'appendMessage'
	| 'updateSession'
	| 'approveSpec'
	| 'sendToArchitect';

export type HostToWebview =
	| { type: 'state'; payload: HqState }
	| { type: 'knowledge'; payload: KnowledgeSnapshot }
	| { type: 'settings'; payload: SettingsCatalog }
	| { type: 'runtimes'; payload: RuntimeSnapshot[] }
	| { type: 'rpcResult'; id: string; result: unknown }
	| { type: 'rpcError'; id: string; error: string };

export type WebviewToHost =
	| { type: 'ready' }
	| { type: 'openFixture' }
	| { type: 'runSynthetic' }
	| { type: 'exportResult' }
	| { type: 'openRecords' }
	| { type: 'refresh' }
	| { type: 'editMcpJson' }
	| { type: 'createSkill'; slug: string }
	| { type: 'readySettings' }
	| { type: 'readyRuntimes' }
	| { type: 'openContextLens' }
	| { type: 'openSettings' }
	| { type: 'newSession'; kind: SessionKind }
	| { type: 'openSession'; id: string }
	| { type: 'archiveSession'; id: string }
	| { type: 'runtimeAction'; sourceId: string; action: RuntimeAction }
	| {
		type: 'saveSettings';
		sourceId: string;
		values: Record<string, unknown>;
		secrets?: Record<string, string>;
		clearSecrets?: string[];
	}
	| { type: 'runSettingsAction'; sourceId: string; actionId: string; values?: Record<string, unknown>; secrets?: Record<string, string> }
	| { type: 'rpc'; id: string; method: RpcMethod; params?: Record<string, unknown> };
