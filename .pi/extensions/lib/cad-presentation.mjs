// Pure presentation helpers: no network, credentials, CAD mutations or SDK state.
export function compactWorkspace(workspace) {
  if (!workspace) return null;
  const commits = workspace.commits ?? [];
  const assets = workspace.assets ?? [];
  return {
    revision: workspace.revision,
    generation: workspace.generation,
    commit_id: workspace.commit_id,
    current_commit: commits.find(c => c.id === workspace.commit_id) ?? null,
    commit_count: commits.length,
    asset_count: assets.length,
    current_asset_count: assets.filter(a => a.commit_id === workspace.commit_id).length,
  };
}

export function historyPage(state, kind, offset = 0, limit = 20, commit) {
  let items;
  if (kind === 'commits') items = [...(state.workspace?.commits ?? [])].reverse();
  else if (kind === 'assets') {
    items = [...(state.workspace?.assets ?? [])].reverse()
      .filter(a => !commit || a.commit_id === commit)
      .map(({note, ...asset}) => ({...asset, note_characters: (note ?? '').length}));
  } else items = kind === 'publications' ? state.publications : state.history;
  items ??= [];
  return {
    revision: state.revision, generation: state.generation,
    workspace: compactWorkspace(state.workspace), kind,
    items: items.slice(offset, offset + limit), total_available: items.length,
    next_offset: offset + limit < items.length ? offset + limit : null,
    ...(kind === 'builds' ? {note: 'Service lists only the latest 100 builds.'} : {}),
    ...(kind === 'assets' ? {note: 'Instructions omitted; use view=asset with asset_id to read one attachment.'} : {}),
  };
}

function present(value) {
  return value != null && (Array.isArray(value) ? value.length > 0 :
    typeof value === 'object' ? Object.values(value).some(present) : true);
}

function evidenceStatus(value) {
  if (!present(value)) return 'not_checked';
  let positive = false, negative = false;
  function walk(v) {
    if (!v || typeof v !== 'object') return;
    for (const [key, child] of Object.entries(v)) {
      if (['passed', 'valid', 'watertight', 'winding_consistent'].includes(key) && typeof child === 'boolean') {
        positive ||= child && ['passed', 'valid'].includes(key);
        negative ||= !child;
      }
      if (['self_intersecting_faces', 'degenerate_faces', 'non_manifold_edges'].includes(key) && typeof child === 'number' && child > 0) negative = true;
      walk(child);
    }
  }
  walk(value);
  // Legacy metric-only reports are evidence, not an invented pass/fail verdict.
  return negative ? 'failed' : positive ? 'passed' : 'reported';
}

export function validationView(report, revision, section = 'summary') {
  const sections = {
    checks: report.checks,
    mesh: report.mesh_validation,
    exports: Object.fromEntries(Object.entries({
      master: report.export_validation,
      tooling: report.casting_box?.part_validation,
    }).filter(([, value]) => present(value))),
    assembly: report.casting_box?.assembly_checks,
  };
  const coverage = Object.fromEntries(Object.entries(sections).map(([name, value]) => [name, {
    status: evidenceStatus(value),
    basis: present(value) ? 'Recorded revision report only; not independent physical verification.' :
      'No evidence recorded for this section. This is NOT a passing check.',
  }]));
  const common = {
    revision, geometry_valid: report.valid ?? null, coverage,
    valid_scope: 'Native geometry and declared assertions ONLY',
    note: 'Geometry validity and declared assertions do not certify mesh exports, collisions, printability or strength. reported means legacy evidence without an explicit pass/fail verdict.',
  };
  if (section === 'all') return {...common, ...report};
  if (section === 'summary') return {
    ...common, valid: report.valid ?? null,
    checks: report.checks, warnings: report.warnings ?? [],
    available_sections: Object.keys(sections).filter(name => present(sections[name])),
    limitations: report.limitations,
  };
  const status = coverage[section].status;
  return {...common, section, status,
    valid: status === 'passed' ? true : status === 'failed' ? false : null,
    results: present(sections[section]) ? sections[section] : null};
}
