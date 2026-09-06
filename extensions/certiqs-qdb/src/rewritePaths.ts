/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

const LEGACY_PREFIX = '/api/qsecdb/';
const CATALOG_PREFIX = '/internal/catalog/';

export function rewriteInternalPath(path: string): string {
	const queryIndex = path.indexOf('?');
	const pathname = queryIndex >= 0 ? path.slice(0, queryIndex) : path;
	const query = queryIndex >= 0 ? path.slice(queryIndex) : '';
	if (!pathname.startsWith(LEGACY_PREFIX)) {
		return path;
	}
	return `${CATALOG_PREFIX}${pathname.slice(LEGACY_PREFIX.length)}${query}`;
}

export function rewriteLookupUrls(value: unknown): unknown {
	if (typeof value === 'string') {
		return value.startsWith(LEGACY_PREFIX) ? rewriteInternalPath(value) : value;
	}
	if (Array.isArray(value)) {
		return value.map(rewriteLookupUrls);
	}
	if (value && typeof value === 'object') {
		const next: Record<string, unknown> = {};
		for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
			next[key] = rewriteLookupUrls(child);
		}
		return next;
	}
	return value;
}
