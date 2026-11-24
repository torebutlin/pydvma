import { expect, test } from 'vitest';
import { get } from 'svelte/store';
import {
  clampFigureWidth, defaultFigureName, figureFormats, figureNotes, figureOptions, figureStem, figureTargets,
} from '../../src/lib/export/figureSave';

test('the default figure name is stamped from the clock, without an extension', () => {
  expect(defaultFigureName(new Date(2026, 9, 26, 9, 5))).toBe('pydvma_figure_2026-10-26_0905');
});

test('the shared figure options start as PNG on white', () => {
  expect(get(figureOptions)).toEqual({ png: true, pdf: false, bg: 'white', widthMm: 160 });
});

test('figureFormats lists the ticked formats, PNG first', () => {
  expect(figureFormats({ png: true, pdf: false, bg: 'white', widthMm: 160 })).toEqual(['png']);
  expect(figureFormats({ png: false, pdf: true, bg: 'white', widthMm: 160 })).toEqual(['pdf']);
  expect(figureFormats({ png: true, pdf: true, bg: 'dark', widthMm: 160 })).toEqual(['png', 'pdf']);
  expect(figureFormats({ png: false, pdf: false, bg: 'white', widthMm: 160 })).toEqual([]);
});

test('figureStem drops a trailing .png / .pdf in any case, and nothing else', () => {
  expect(figureStem('/lab/beam.png')).toBe('/lab/beam');
  expect(figureStem('beam.PDF')).toBe('beam');
  expect(figureStem('beam.v2')).toBe('beam.v2');
  expect(figureStem('beam')).toBe('beam');
});

test('one format: the name\'s own .png / .pdf decides, else the ticked format is added', () => {
  expect(figureTargets('/lab/beam.png', ['png'])).toEqual([{ name: '/lab/beam.png', format: 'png' }]);
  // Typing beam.pdf in the Save dialog saves a PDF, not beam.pdf.png.
  expect(figureTargets('/lab/beam.pdf', ['png'])).toEqual([{ name: '/lab/beam.pdf', format: 'pdf' }]);
  expect(figureTargets('/lab/beam.PNG', ['pdf'])).toEqual([{ name: '/lab/beam.PNG', format: 'png' }]);
  expect(figureTargets('beam', ['pdf'])).toEqual([{ name: 'beam.pdf', format: 'pdf' }]);
});

test('both formats: one name, two files side by side', () => {
  expect(figureTargets('/lab/beam.png', ['png', 'pdf'])).toEqual([
    { name: '/lab/beam.png', format: 'png' },
    { name: '/lab/beam.pdf', format: 'pdf' },
  ]);
  expect(figureTargets('C:\\lab\\beam.pdf', ['png', 'pdf'])).toEqual([
    { name: 'C:\\lab\\beam.png', format: 'png' },
    { name: 'C:\\lab\\beam.pdf', format: 'pdf' },
  ]);
  expect(figureTargets('beam', ['png', 'pdf'])).toEqual([
    { name: 'beam.png', format: 'png' },
    { name: 'beam.pdf', format: 'pdf' },
  ]);
});

test('clampFigureWidth keeps the width in 40-300 mm and falls back to 160', () => {
  expect(clampFigureWidth(90)).toBe(90); expect(clampFigureWidth('120')).toBe(120);
  expect(clampFigureWidth(20)).toBe(40); expect(clampFigureWidth(500)).toBe(300);
  expect(clampFigureWidth(NaN)).toBe(160); expect(clampFigureWidth('')).toBe(160); expect(clampFigureWidth(undefined)).toBe(160);
});

test('figureNotes says when a figure grew, and names glyphs the PDF lacks only when writing a PDF', () => {
  const t = (text: string) => ({ text, role: 'legend' as const, box: { x: 0, y: 0, w: 1, h: 1 } });
  expect(figureNotes({ grown: true, texts: [] }, ['png']).grown)
    .toBe('laid out taller than its usual shape so the labels fit at 10 pt');
  expect(figureNotes({ grown: false, texts: [t('漢 set')] }, ['png']).glyphs).toBeNull();
  expect(figureNotes({ grown: false, texts: [t('漢 set')] }, ['png', 'pdf']).glyphs)
    .toBe("The PDF can't draw 漢: those characters print as boxes there. The PNG shows them.");
  expect(figureNotes({ grown: false, texts: [t('ok')] }, ['pdf'])).toEqual({ grown: null, glyphs: null });
});
