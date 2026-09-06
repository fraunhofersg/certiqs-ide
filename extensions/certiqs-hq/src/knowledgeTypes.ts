/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export const LOOM_VERSION = 3;
export const INPUT_TOKEN_BUDGET = 840_000;
export const RESERVED_OUTPUT_TOKENS = 210_000;
export const SYSTEM_TOKEN_BASE = 8538;

export type LoomCategory =
	| 'Protocol'
	| 'Optical path'
	| 'Key processing'
	| 'Threat model'
	| 'Open questions'
	| string;

export type LoomEntry = {
	id: string;
	category: string;
	title: string;
	body: string;
	source?: string;
	hidden?: boolean;
	updatedAt: string;
};

export type LoomFile = {
	version: number;
	projectName: string;
	createdAt: string;
	updatedAt: string;
	lastHardenedAt: string | null;
	messages: unknown[];
	entries: LoomEntry[];
};

export type WikiStrategy = 'all' | 'auto' | 'manual' | 'index';

export type WikiFile = {
	strategy: WikiStrategy;
	autoDetected: string[];
	manual: string[];
};

export type SessionKind = 'chat' | 'brainstorm' | 'architect';

export type KnotEntry = {
	id: string;
	title: string;
	body: string;
	hidden?: boolean;
	updatedAt: string;
};

export type ChatMessage = {
	id: string;
	role: 'user' | 'system' | 'note';
	text: string;
	createdAt: string;
};

export type BrainstormBranch = {
	id: string;
	title: string;
	body: string;
	selected?: boolean;
};

export type ArchitectStep = {
	id: string;
	title: string;
	body: string;
	done?: boolean;
};

export type SessionFile = {
	id: string;
	kind: SessionKind;
	title: string;
	archived: boolean;
	knot: KnotEntry[];
	messages: ChatMessage[];
	intent?: string;
	branches?: BrainstormBranch[];
	spec?: string;
	specPath?: string;
	steps?: ArchitectStep[];
	specSource?: string;
	updatedAt: string;
};

export type SessionSummary = {
	id: string;
	kind: SessionKind;
	title: string;
	archived: boolean;
	updatedAt: string;
};

export type TokenBudget = {
	input: number;
	reservedOutput: number;
	loom: number;
	wiki: number;
	knot: number;
	system: number;
};

export type KnowledgeSnapshot = {
	loom: LoomFile;
	wiki: WikiFile;
	sessions: SessionSummary[];
	activeSession?: SessionFile;
	tokens: TokenBudget;
	workspaceName: string;
	notice: string;
};

export function estimateTokens(text: string): number {
	return Math.max(0, Math.ceil(text.length / 4));
}

export function emptyLoom(projectName: string, now = new Date().toISOString()): LoomFile {
	return {
		version: LOOM_VERSION,
		projectName,
		createdAt: now,
		updatedAt: now,
		lastHardenedAt: null,
		messages: [],
		entries: [],
	};
}

export function emptyWiki(): WikiFile {
	return { strategy: 'all', autoDetected: [], manual: [] };
}

export function newId(prefix: string): string {
	return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
