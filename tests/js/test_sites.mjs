/**
 * Unit tests for formatRelative() in webui_app/static/js/sites.js
 *
 * Run with: node --test tests/js/test_sites.mjs
 *
 * Uses Node.js built-in node:test + node:assert (no external deps).
 * Inlines formatRelative() — any divergence from sites.js is a bug.
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

// ── Inline formatRelative (MUST stay in sync with sites.js) ──────────────

function formatRelative(isoStr) {
  if (!isoStr) return null;
  const diff = (new Date(isoStr) - Date.now()) / 1000;
  if (!isFinite(diff) || diff < 0) return '排程中…';
  if (diff < 3600) return `${Math.ceil(diff / 60)} 分鐘後`;
  if (diff < 86400) return `${Math.ceil(diff / 3600)} 小時後`;
  return `${Math.ceil(diff / 86400)} 天後`;
}

// ── Helpers ───────────────────────────────────────────────────────────────

const _realDateNow = Date.now;

function freezeNow(epochMs) {
  Date.now = () => epochMs;
}

function isoAt(epochMs) {
  return new Date(epochMs).toISOString();
}

// ── Tests ─────────────────────────────────────────────────────────────────

describe('formatRelative', () => {
  const NOW = 1_750_000_000_000; // fixed epoch for all tests

  beforeEach(() => freezeNow(NOW));
  afterEach(() => { Date.now = _realDateNow; });

  test('null input returns null', () => {
    assert.equal(formatRelative(null), null);
  });

  test('empty string returns null', () => {
    assert.equal(formatRelative(''), null);
  });

  test('invalid ISO string returns 排程中…', () => {
    assert.equal(formatRelative('not-a-date'), '排程中…');
  });

  test('past time returns 排程中…', () => {
    const past = isoAt(NOW - 1000);
    assert.equal(formatRelative(past), '排程中…');
  });

  test('30 seconds in future returns 1 分鐘後', () => {
    const soon = isoAt(NOW + 30_000);
    assert.equal(formatRelative(soon), '1 分鐘後');
  });

  test('exactly 3599 seconds returns 60 分鐘後', () => {
    const soon = isoAt(NOW + 3_599_000);
    assert.equal(formatRelative(soon), '60 分鐘後');
  });

  test('2 hours in future returns 2 小時後', () => {
    const twoH = isoAt(NOW + 2 * 3600_000);
    assert.equal(formatRelative(twoH), '2 小時後');
  });

  test('23 hours 59 minutes returns 24 小時後 (ceil)', () => {
    const almostDay = isoAt(NOW + (24 * 3600 - 60) * 1000);
    assert.equal(formatRelative(almostDay), '24 小時後');
  });

  test('exactly 24 hours returns 1 天後', () => {
    const oneDay = isoAt(NOW + 86_400_000);
    assert.equal(formatRelative(oneDay), '1 天後');
  });

  test('3 days in future returns 3 天後', () => {
    const threeDays = isoAt(NOW + 3 * 86_400_000);
    assert.equal(formatRelative(threeDays), '3 天後');
  });
});
