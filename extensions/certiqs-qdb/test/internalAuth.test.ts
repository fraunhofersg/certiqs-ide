import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { describe, it } from 'node:test';
import { generateInternalAuthSecret, signInternalToken } from '../src/internalAuth';

describe('internal auth', () => {
	it('mints an HS256 token with sub, is_admin, iat, and exp', () => {
		const secret = 'unit-test-secret';
		const token = signInternalToken({
			userId: 'alice',
			isAdmin: true,
			secret,
			ttlSeconds: 60,
			nowSeconds: 1_700_000_000,
		});
		const [header, payload, signature] = token.split('.');
		assert.ok(header);
		assert.ok(payload);
		const expected = createHmac('sha256', secret).update(`${header}.${payload}`).digest('base64url');
		assert.equal(signature, expected);
		const claims = JSON.parse(Buffer.from(payload, 'base64url').toString());
		assert.equal(claims.sub, 'alice');
		assert.equal(claims.is_admin, true);
		assert.equal(claims.iat, 1_700_000_000);
		assert.equal(claims.exp, 1_700_000_060);
	});

	it('omits a usable identity when userId is null', () => {
		const token = signInternalToken({
			userId: null,
			isAdmin: false,
			secret: 'x',
			ttlSeconds: 60,
			nowSeconds: 10,
		});
		const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
		assert.equal(payload.sub, null);
		assert.equal(payload.is_admin, false);
	});

	it('generates a non-empty secret', () => {
		assert.ok(generateInternalAuthSecret().length >= 32);
	});
});
