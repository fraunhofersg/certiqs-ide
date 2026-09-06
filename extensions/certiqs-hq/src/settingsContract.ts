/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export type SettingsFieldKind = 'text' | 'number' | 'toggle' | 'secret' | 'status' | 'action' | 'select' | 'interpreter';

export type InterpreterInfo = {
	path: string;
	version: string;
	minor: string;
	compatible: boolean;
	netsquid?: string;
};

export type SettingsSelectOption = {
	value: string;
	label: string;
	preview?: string;
};

export type SettingsField = {
	kind: SettingsFieldKind;
	id: string;
	label?: string;
	description?: string;
	placeholder?: string;
	setting?: string;
	secretKey?: string;
	options?: SettingsSelectOption[];
	variant?: 'primary' | 'outline' | 'ghost' | 'danger';
};

export type SettingsSection = {
	id: string;
	title: string;
	description?: string;
	icon?: 'flask' | 'gear' | 'info';
	order?: number;
	fields: SettingsField[];
};

export type SettingsManifest = {
	id: string;
	title: string;
	order?: number;
	sections: SettingsSection[];
};

export type SettingsSnapshot = {
	values: Record<string, string | number | boolean>;
	secretSet: Record<string, boolean>;
	status: Record<string, string>;
	interpreters?: InterpreterInfo[];
};

export type SettingsSourceState = SettingsManifest & SettingsSnapshot;

export type SettingsCatalog = {
	sources: SettingsSourceState[];
};

export type SettingsCommand =
	| { type: 'describe' }
	| { type: 'get' }
	| { type: 'set'; values: Record<string, unknown>; secrets?: Record<string, string>; clearSecrets?: string[] }
	| { type: 'action'; id: string };

export type CertiqsSettingsContribution = {
	id: string;
	command: string;
};
