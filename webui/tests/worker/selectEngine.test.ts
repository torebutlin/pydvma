// selectEngine.test.ts — the engine-host POLICY, tested as a pure function.
//
// Stage 1 (Task 8) is opt-in: only an explicit `?enginehost=` asks for the
// native host. Task 10 extends `parseEngineParam`'s caller with
// served-by-pydvma-serve auto-detection; the param's own meaning must not
// drift when it does, which is what these pin.
import { describe, expect, test } from 'vitest';
import { parseEngineParam } from '../../src/lib/worker/selectEngine';

describe('parseEngineParam (stage-1 opt-in policy)', () => {
  test('no param expresses no preference at all', () => {
    // null (not {kind:'pyodide'}) — Task 10 needs "unstated" to be
    // distinguishable from "explicitly asked for the browser engine".
    expect(parseEngineParam(null)).toBeNull();
    expect(parseEngineParam('')).toBeNull();
  });

  test('pyodide forces the browser worker', () => {
    expect(parseEngineParam('pyodide')).toEqual({ kind: 'pyodide' });
  });

  test('native means the same-origin /engine endpoint', () => {
    expect(parseEngineParam('native')).toEqual({ kind: 'native', url: 'same-origin' });
  });

  test('any other value is an explicit ws URL (the e2e cross-origin form)', () => {
    expect(parseEngineParam('ws://127.0.0.1:8764/engine'))
      .toEqual({ kind: 'native', url: 'ws://127.0.0.1:8764/engine' });
    expect(parseEngineParam('wss://host:9/engine'))
      .toEqual({ kind: 'native', url: 'wss://host:9/engine' });
  });
});
