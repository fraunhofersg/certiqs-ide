/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export const PROCESS_LABELS = [
	'synthetic',
	'not a measurement',
	'not a security or conformity statement',
] as const;

export type Origin = 'synthetic';
export type RunState = 'created' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface RecordRef {
	id: string;
	kind: 'goal' | 'requirement' | 'procedure' | 'finding' | 'run';
	sourceUri: string;
	revision: string;
}

export interface Finding {
	id: string;
	recordRef: RecordRef;
	summary: string;
	evidence: 'present' | 'missing' | 'stale';
}

export interface Result {
	schemaVersion: 'certiqs-result/0.1';
	runId: string;
	fixtureRef: RecordRef;
	procedureRef: RecordRef;
	state: RunState;
	origin: Origin;
	labels: typeof PROCESS_LABELS;
	startedAt?: string;
	endedAt?: string;
	findings: readonly Finding[];
	limitations: readonly string[];
}

export interface Fixture {
	schema_version: string;
	fixture_id: string;
	origin: string;
	notice: string;
	target: { id: string; name: string };
	procedure: { id: string; version: string; purpose: string };
	assumptions: readonly { id: string; statement: string; status: string }[];
	display_observations: readonly { id: string; label: string; value: string; scientific_interpretation: null }[];
	evidence_availability: { fixture: string; calibration: string };
	run: null;
}
