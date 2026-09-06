import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { decodeTreeParam, emptyGroup, encodeTreeParam } from '../webview/src/lib/search';

describe('search tree codec', () => {
	it('round-trips a condition group', () => {
		const tree = emptyGroup('OR');
		tree.children.push({
			id: 'c1',
			kind: 'condition',
			field: 'vuln_name',
			operator: 'contains',
			value: { text: 'photon' },
		});
		const encoded = encodeTreeParam(tree);
		assert.deepEqual(decodeTreeParam(encoded), tree);
	});

	it('degrades to an empty group on garbage', () => {
		const fallback = decodeTreeParam('%not-json%');
		assert.equal(fallback.kind, 'group');
		assert.equal(fallback.children.length, 0);
	});
});
