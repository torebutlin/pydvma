import { expect, test } from 'vitest';
import { summariseColumn } from '../../src/lib/stores/channelSummary';

test('empty column summarises to off', () => {
  expect(summariseColumn([])).toBe('off');
});

test('all-on summarises to on', () => {
  expect(summariseColumn(['on', 'on', 'on'])).toBe('on');
});

test('all-off summarises to off', () => {
  expect(summariseColumn(['off', 'off'])).toBe('off');
});

test('all-fade summarises to fade', () => {
  expect(summariseColumn(['fade', 'fade'])).toBe('fade');
});

test('mixed on+fade summarises to mixed', () => {
  expect(summariseColumn(['on', 'fade'])).toBe('mixed');
});

test('mixed on+off summarises to mixed', () => {
  expect(summariseColumn(['on', 'off', 'on'])).toBe('mixed');
});

test('mixed fade+off summarises to mixed', () => {
  expect(summariseColumn(['fade', 'off'])).toBe('mixed');
});

test('single value summarises to that state', () => {
  expect(summariseColumn(['on'])).toBe('on');
  expect(summariseColumn(['fade'])).toBe('fade');
  expect(summariseColumn(['off'])).toBe('off');
});
