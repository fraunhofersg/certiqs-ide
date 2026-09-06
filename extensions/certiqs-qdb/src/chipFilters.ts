/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export type ChipRow = {
	encoding?: string | null;
	encodings?: string[] | null;
	architecture?: string | null;
	architectures?: string[] | null;
	module?: string | null;
	component?: string | null;
};

export type ChipSelection = {
	encodings: readonly string[];
	architectures: readonly string[];
	modules: readonly string[];
	components: readonly string[];
};

export function parseCsvTokens(value: string | null | undefined): string[] {
	if (!value) {
		return [];
	}
	return value.split(',').map(token => token.trim()).filter(Boolean);
}

/**
 * Directory filter chips. Not engine logic.
 * Encoding/architecture NULL = wildcard (still shown when a chip is on).
 * Module/component NULL = excluded once any chip on that axis is active.
 */
export function chipMatches(
	row: ChipRow,
	chips: ChipSelection,
	normalizeComponent: (component: string | null) => string[],
): boolean {
	if (chips.encodings.length) {
		const values = row.encodings ?? (row.encoding ? [row.encoding] : []);
		if (values.length && !values.some(value => chips.encodings.includes(value))) {
			return false;
		}
	}
	if (chips.architectures.length) {
		const values = row.architectures ?? (row.architecture ? [row.architecture] : []);
		if (values.length && !values.some(value => chips.architectures.includes(value))) {
			return false;
		}
	}
	if (chips.modules.length) {
		if (!row.module) {
			return false;
		}
		const tokens = parseCsvTokens(row.module);
		if (!tokens.some(token => chips.modules.includes(token))) {
			return false;
		}
	}
	if (chips.components.length) {
		if (!row.component) {
			return false;
		}
		const names = normalizeComponent(row.component);
		if (!names.some(name => chips.components.includes(name))) {
			return false;
		}
	}
	return true;
}
