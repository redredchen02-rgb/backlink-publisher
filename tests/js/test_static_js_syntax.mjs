/**
 * Regression guard — Plan 2026-06-18-002 / legacy-js.
 *
 * Walks webui_app/static/js/** and runs `node --check` on every .js file.
 * Any parse error (e.g. an orphaned top-level brace left behind by a refactor)
 * fails the test with the file path + the exact node diagnostic, so a broken
 * ES module can never again ship silently to every legacy Jinja page
 * (/, /ce:history, /sites, /batch-campaign) and kill the notification
 * bell / toast / error-report wiring for over a week (see fix 85a9e1a7).
 *
 * The Vue SPA source (frontend/src) is NOT covered here on purpose: it is
 * syntax-checked by `npx tsc --noEmit` + `npx vite build` in CI, which
 * would catch the same class of error. This guard closes the gap that the
 * SPA lane's path filter (frontend/**) does not reach the legacy modules.
 *
 * Run with: node --test tests/js/test_static_js_syntax.mjs
 *
 * Uses Node.js built-in node:test + node:assert + node:child_process
 * (no external deps). Self-locates the repo root from this file's URL so it
 * works regardless of the current working directory.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const THIS_DIR = path.dirname(fileURLToPath(import.meta.url));
// tests/js/test_static_js_syntax.mjs -> repo root is two levels up.
const REPO_ROOT = path.resolve(THIS_DIR, '..', '..');
const STATIC_JS_DIR = path.join(REPO_ROOT, 'webui_app', 'static', 'js');

function collectJsFiles(dir) {
    const out = [];
    const walk = (current) => {
        for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
            const full = path.join(current, entry.name);
            if (entry.isDirectory()) {
                if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
                walk(full);
            } else if (entry.isFile() && entry.name.endsWith('.js')) {
                out.push(full);
            }
        }
    };
    walk(dir);
    return out.sort();
}

describe('legacy static JS syntax (node --check)', () => {
    const files = collectJsFiles(STATIC_JS_DIR);

    test('found the legacy static/js tree', () => {
        assert.ok(files.length > 0, `No .js files found under ${STATIC_JS_DIR}`);
    });

    for (const file of files) {
        const rel = path.relative(REPO_ROOT, file);
        test(`syntax OK: ${rel}`, () => {
            let stdout;
            try {
                // node --check parses the file as a module and exits 0 on success.
                stdout = execFileSync('node', ['--check', file], {
                    encoding: 'utf8',
                    stdio: ['ignore', 'pipe', 'pipe'],
                });
            } catch (err) {
                const detail = (err.stderr || err.stdout || err.message || '').trim();
                assert.fail(`Syntax error in ${rel}:\n${detail}`);
            }
            assert.equal(typeof stdout, 'string');
        });
    }
});
