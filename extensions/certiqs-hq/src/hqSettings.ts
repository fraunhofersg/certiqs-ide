/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { PROCESS_LABELS } from './protocol';
import { SettingsManifest, SettingsSourceState } from './settingsContract';

export async function loadHqSettings(extensionUri: vscode.Uri): Promise<SettingsSourceState> {
	const manifest = await readHqManifest(extensionUri);
	const folder = vscode.workspace.workspaceFolders?.[0];
	const values: Record<string, string | number | boolean> = {};
	for (const field of hqFields(manifest)) {
		if (!field.setting) {
			continue;
		}
		const [section, key] = splitSetting(field.setting);
		const current = vscode.workspace.getConfiguration(section).get(key);
		if (typeof current === 'string' || typeof current === 'number' || typeof current === 'boolean') {
			values[field.id] = current;
		}
	}
	return {
		...manifest,
		values,
		secretSet: {},
		status: {
			workspace: folder ? folder.name : 'No workspace folder',
			labels: PROCESS_LABELS.join(' · '),
		},
	};
}

export async function applyHqSettings(extensionUri: vscode.Uri, values: Record<string, unknown>): Promise<void> {
	const manifest = await readHqManifest(extensionUri);
	const byId = new Map(hqFields(manifest).map(field => [field.id, field]));
	for (const [id, value] of Object.entries(values)) {
		const field = byId.get(id);
		if (!field?.setting) {
			continue;
		}
		const [section, key] = splitSetting(field.setting);
		await vscode.workspace.getConfiguration(section).update(key, value, vscode.ConfigurationTarget.Global);
	}
}

async function readHqManifest(extensionUri: vscode.Uri): Promise<SettingsManifest> {
	const uri = vscode.Uri.joinPath(extensionUri, 'settings.json');
	const raw = await vscode.workspace.fs.readFile(uri);
	return JSON.parse(new TextDecoder().decode(raw)) as SettingsManifest;
}

function hqFields(manifest: SettingsManifest) {
	return manifest.sections.flatMap(section => section.fields);
}

function splitSetting(setting: string): [string, string] {
	const index = setting.lastIndexOf('.');
	return [setting.slice(0, index), setting.slice(index + 1)];
}
