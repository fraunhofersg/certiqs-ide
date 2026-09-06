import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { rewriteInternalPath, rewriteLookupUrls } from '../src/rewritePaths';

describe('legacy field-picker paths', () => {
	it('rewrites /api/qsecdb catalogue URLs onto /internal/catalog', () => {
		assert.equal(rewriteInternalPath('/api/qsecdb/component-types'), '/internal/catalog/component-types');
		assert.equal(
			rewriteInternalPath('/api/qsecdb/attack-categories?q=side'),
			'/internal/catalog/attack-categories?q=side',
		);
	});

	it('leaves /internal paths unchanged', () => {
		assert.equal(rewriteInternalPath('/internal/systems'), '/internal/systems');
	});

	it('rewrites nested lookup urls in field metadata', () => {
		const rewritten = rewriteLookupUrls({
			options: { url: '/api/qsecdb/protocols', valueKey: 'name' },
		}) as { options: { url: string } };
		assert.equal(rewritten.options.url, '/internal/catalog/protocols');
	});
});
