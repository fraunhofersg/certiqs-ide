import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { chipMatches } from '../src/chipFilters';
import { normalizeComponentTerms } from '../webview/src/lib/qkd/componentTerms';

describe('directory chips', () => {
	it('treats encoding NULL as a wildcard that still shows when a chip is on', () => {
		assert.equal(
			chipMatches(
				{ encoding: null, module: 'Transmitter', component: 'Laser Source' },
				{ encodings: ['DV'], architectures: [], modules: [], components: [] },
				normalizeComponentTerms,
			),
			true,
		);
	});

	it('excludes a NULL module once any module chip is active', () => {
		assert.equal(
			chipMatches(
				{ module: null, component: 'Laser Source' },
				{ encodings: [], architectures: [], modules: ['Transmitter'], components: [] },
				normalizeComponentTerms,
			),
			false,
		);
	});

	it('matches CSV module tokens', () => {
		assert.equal(
			chipMatches(
				{ module: 'Transmitter, Receiver', component: 'detector' },
				{ encodings: [], architectures: [], modules: ['Receiver'], components: [] },
				normalizeComponentTerms,
			),
			true,
		);
	});

	it('normalises component synonyms including one-to-many detector', () => {
		assert.equal(
			chipMatches(
				{ module: 'Receiver', component: 'detector' },
				{ encodings: [], architectures: [], modules: [], components: ['Single-Photon Detector'] },
				normalizeComponentTerms,
			),
			true,
		);
	});
});
