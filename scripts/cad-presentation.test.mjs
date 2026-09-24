import {test} from 'node:test';
import assert from 'node:assert/strict';
import {compactWorkspace, historyPage, validationView} from '../.pi/extensions/lib/cad-presentation.mjs';

const workspace = {
  revision: 'current', generation: 19, commit_id: 'c19',
  commits: Array.from({length: 19}, (_, i) => ({id: `c${i+1}`, name: `S${i+1}`})),
  assets: Array.from({length: 150}, (_, i) => ({id: `a${i}`, commit_id: i<148?'old':'c19', role: 'print', note: 'private instructions '.repeat(800)})),
};

test('compact header does not grow with attachment instructions', () => {
  const result = compactWorkspace(workspace);
  assert.ok(JSON.stringify(result).length < 1000);
  assert.equal(result.current_commit.id, 'c19');
  assert.equal(result.commit_count, 19);
  assert.equal(result.asset_count, 150);
  assert.equal(result.current_asset_count, 2);
  assert.equal(result.assets, undefined);
});

test('bounded asset and commit pages, instructions omitted, no input mutation', () => {
  const state = {workspace};
  const first = historyPage(state, 'assets', 0, 10);
  assert.equal(first.items.length, 10);
  assert.equal(first.next_offset, 10);
  assert.equal(first.items[0].id, 'a149');
  assert.equal(first.items[0].note, undefined);
  assert.ok(first.items[0].note_characters > 10000);
  assert.ok(workspace.assets[0].note.length > 10000);
  assert.equal(historyPage(state, 'assets', 140, 10).next_offset, null);
  assert.equal(historyPage(state, 'assets', 0, 10, 'c19').total_available, 2);
  assert.equal(historyPage(state, 'commits', 0, 1).items[0].id, 'c19');
  assert.equal(workspace.commits[0].id, 'c1');
});

test('missing evidence cannot inherit geometry valid=true', () => {
  const report = {valid: true, checks: [{passed: true}]};
  const summary = validationView(report, 'rev');
  assert.equal(summary.valid, true);
  assert.deepEqual(summary.available_sections, ['checks']);
  for (const section of ['mesh', 'exports', 'assembly']) {
    const result = validationView(report, 'rev', section);
    assert.equal(result.geometry_valid, true);
    assert.equal(result.status, 'not_checked');
    assert.equal(result.valid, null);
    assert.equal(result.results, null);
  }
  assert.equal(summary.coverage.checks.status, 'passed');
});

test('failed predicates win; metric-only legacy reports are not invented passes', () => {
  const report = {valid: true, checks: [{passed: true}, {passed: false}],
    mesh_validation: {watertight: true, winding_consistent: true, triangles: 100},
    export_validation: {stl: {valid: true, self_intersecting_faces: 1}},
    casting_box: {assembly_checks: {minimum_clearance: 0.2}}};
  const result = validationView(report, 'rev', 'all');
  assert.equal(result.coverage.checks.status, 'failed');
  assert.equal(result.coverage.exports.status, 'failed');
  assert.equal(result.coverage.mesh.status, 'reported');
  assert.equal(result.coverage.assembly.status, 'reported');
  assert.equal(validationView(report, 'rev', 'assembly').valid, null);
});

test('empty sections are not advertised as available', () => {
  const result = validationView({valid:true, checks:[], mesh_validation:{}, export_validation:{}, casting_box:{part_validation:{}, assembly_checks:{}}}, 'rev');
  assert.deepEqual(result.available_sections, []);
  assert.ok(Object.values(result.coverage).every(x => x.status === 'not_checked'));
});
