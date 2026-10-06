import type { APIRoute, GetStaticPaths } from 'astro';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { dataRoot, datasets, defaultDataset, getData, metrics } from '../../lib/data';
import { extractionCoverage, publicImpact } from '../../lib/metrics';
import { partyInsights } from '../../lib/party-insights';
import { votingComparisons, votingCoverage, votingPatterns } from '../../lib/voting';
import { experiments } from '../../lib/experiments';
import { jsonBody } from '../../lib/json-stream';
import { readingIndex, productionProgress, readingProgress } from '../../lib/readings';

export const prerender = true;

function markdown(relative: string, dataset: string) {
  const resolved = path.resolve(dataRoot, relative);
  const allowed = path.join(dataRoot, dataset) + path.sep;
  if (!resolved.startsWith(allowed) || !resolved.endsWith('.md')) throw new Error('Unsafe Markdown source path');
  return fs.readFileSync(resolved, 'utf8');
}

export const getStaticPaths: GetStaticPaths = () => {
  // Keep shared canonical objects, not a serialized copy for every route plus every bulk list.
  // Large law corpora otherwise multiply build memory before the first endpoint is written.
  const routes: { params: { path: string }; props: { value: unknown; contentType: string } }[] = [];
  const add = (url: string, value: unknown, contentType = 'application/json; charset=utf-8') => routes.push({
    params: { path: url }, props: { value, contentType },
  });
  const collections = ['parties', 'programs', 'criteria', 'laws', 'impacts', 'votes'] as const;
  for (const dataset of datasets) {
    const data = getData(dataset);
    const prefix = `v1/${dataset}`;
    const coverageDir = path.join(dataRoot, dataset, 'coverage');
    const coverage = fs.existsSync(coverageDir) ? fs.readdirSync(coverageDir).filter(f => f.endsWith('.json')).sort().map(f => JSON.parse(fs.readFileSync(path.join(coverageDir, f), 'utf8'))) : [];
    add(`${prefix}/coverage.json`, { schema_version: '1.0', dataset, total: coverage.length, items: coverage });
    add(`${prefix}/voting-coverage.json`, data.votingCoverage ?? { schema_version: '1.0', dataset, items: [], note: 'Voting enrichment has not yet checked these laws.' });
    add(`${prefix}/voting-summary.json`, {
      schema_version: '1.0', dataset, coverage: votingCoverage(data), items: votingPatterns(data),
      position_unit: 'Distinct imported law with a unique confirmed final whole-law vote and a documented faction position.',
      comparison_unit: 'Law × criterion × faction; multiple criteria on one law are correlated, not independent promise breaches.',
      note: 'No party ranking, no inferred coalition votes, no absence-as-opposition. Split ballots are never replaced by a majority label. Only accepted Sol-final or editorial law effects and programmes valid before the vote are compared. Tensions are not proof of broken promises.',
    });
    const comparisons = votingComparisons(data);
    add(`${prefix}/voting-comparisons.json`, {
      schema_version: '1.0', dataset, total: comparisons.length,
      method: 'Directional comparison, not fulfilment or motivation. Only confirmed final whole-law votes and published law effects; abstention/absence are not opposition.',
      items: comparisons.map(c => ({ id: c.id, vote_id: c.vote.id, law_id: c.law.id, impact_id: c.impact.id,
        criterion_id: c.criterion.id, program_id: c.program.id, party_id: c.party.id, group: c.group.group,
        date: c.vote.date, score: c.impact.score, position: c.position, outcome: c.outcome,
        consistent_ballots: c.consistent_ballots, tension_ballots: c.tension_ballots,
        vote_url: `/api/${prefix}/votes/${c.vote.id}.json`, impact_url: `/api/${prefix}/impacts/${c.impact.id}.json`,
        criterion_url: `/api/${prefix}/criteria/${c.criterion.id}.json`,
      })),
    });
    const reports = experiments(dataset);
    // Keep the old v1 aliases for existing consumers, not as a second data product.
    add(`${prefix}/experiments.json`, { schema_version: '1.0', dataset, total: reports.length, items: reports });
    add(`${prefix}/analyses.json`, { schema_version: '1.0', dataset, total: reports.length, items: reports });
    add(`${prefix}/analysis.json`, productionProgress() ?? { schema_version: '1.0', status: 'not_started',
      note: 'Production all-party queue has not published a checkpoint yet; existing programme audits remain available.',
      programmes: reports.map(r => ({ program_id: r.program_id, laws_completed: r.laws.filter(l => l.status === 'completed').length, total_laws: r.law_ids.length })) });
    for (const report of reports) {
      add(`${prefix}/experiments/${report.program_id}.json`, report);
      add(`${prefix}/analyses/${report.program_id}.json`, report);
    }
    const readings = readingIndex();
    add(`${prefix}/reading-progress.json`, readingProgress() ?? { status: 'not_started' });
    add(`${prefix}/readings.json`, { schema_version: '1.0', dataset, total: readings.length,
      items: readings.map(({ pages, ...record }) => ({ ...record, warning_pages: pages.filter(p => p.warnings.length).map(p => p.number) })) });
    for (const reading of readings) {
      add(`${prefix}/readings/${reading.document_id}.json`, reading);
      add(`${prefix}/readings/${reading.document_id}/source.md`, markdown(reading.markdown_path, dataset), 'text/markdown; charset=utf-8');
    }
    const dataDigest = createHash('sha256').update(JSON.stringify(reports.length ? { ...data, experiments: reports } : data)).digest('hex');
    const acceptedImpacts = data.impacts.filter(publicImpact);
    add(`${prefix}/accepted-impacts.json`, { schema_version: '1.0', dataset, total: acceptedImpacts.length, items: acceptedImpacts });
    const statistics = data.programs.map(p => ({
      program_id: p.id, party_id: p.party_id, election_year: p.election_year,
      period_start: p.period_start, period_end: p.period_end,
      extraction: extractionCoverage(p, data.criteria),
      ...metrics(data.criteria.filter(c => c.program_id === p.id), data.impacts, [p]),
    }));
    add(`${prefix}/extraction.json`, {
      schema_version: '1.0', dataset, total: data.programs.length, unit: 'source_leaf',
      note: 'Only imported programmes. Processed leaves are not proof of complete commitment extraction or human review; unimported parties are not covered.',
      items: data.programs.map(program => ({ program_id: program.id, party_id: program.party_id,
        ...extractionCoverage(program, data.criteria) })),
    });
    add(`${prefix}/index.json`, {
      schema_version: '1.0', dataset, data_sha256: dataDigest,
      methodology: 'Luna screens; Sol Flex makes final link and overall statutory assessments. Human corrections override generated results.',
      collections: Object.fromEntries(collections.map(c => [c, `/api/${prefix}/${c}.json`])),
      counts: { ...Object.fromEntries(collections.map(c => [c, data[c].length])), accepted_impacts: acceptedImpacts.length },
      accepted_impacts: `/api/${prefix}/accepted-impacts.json`,
      voting_coverage: `/api/${prefix}/voting-coverage.json`, voting_summary: `/api/${prefix}/voting-summary.json`,
      voting_comparisons: `/api/${prefix}/voting-comparisons.json`,
      statistics: `/api/${prefix}/stats.json`, search: `/api/${prefix}/search.json`, coverage: `/api/${prefix}/coverage.json`,
      extraction: `/api/${prefix}/extraction.json`, analyses: `/api/${prefix}/analyses.json`,
      progress: `/api/${prefix}/analysis.json`, readings: `/api/${prefix}/readings.json`,
      experiments: `/api/${prefix}/experiments.json`,
      filters: 'Static snapshot API. No server-side query parameters. Filter items client-side or use the search index.',
    });
    for (const collection of collections) {
      const items = data[collection];
      add(`${prefix}/${collection}.json`, { schema_version: '1.0', dataset, total: items.length, items });
      for (const item of items) add(`${prefix}/${collection}/${item.id}.json`,
        collection === 'parties' ? {
          ...item, dataset, programs: data.programs.filter(p => p.party_id === item.id).map(p => p.id),
          statistics: statistics.filter(s => s.party_id === item.id),
          insights: {
            method: '/methodik/#parteibilanz', timeline_basis: 'current_accepted_evidence_by_law_publication_month',
            fulfilment_history_available: false, law_groups_overlap: true,
            periods: [...new Set(data.programs.filter(p => p.party_id === item.id && p.review.status !== 'rejected').map(p => p.election_year))]
              .sort((a, b) => b - a).map(year => ({ election_year: year,
                ...partyInsights(data, data.programs.filter(p => p.party_id === item.id && p.election_year === year)),
              })),
          },
        } : item);
    }
    add(`${prefix}/stats.json`, {
      schema_version: '1.0', dataset, unit: 'criterion', method: '/methodik/',
      denominator: 'All non-rejected criteria in the programme, including unassessed ones. Null for zero denominator.',
      note: 'Final Sol assessments count automatically; editorial corrections take precedence. Overall criterion scores are synthesized from accepted law effects, not sums. Unknown criteria remain in the denominator. Alignment is the mean signed score of assessed criteria only, not a percent fulfilled.',
      items: statistics,
    });
    add(`${prefix}/search.json`, { schema_version: '1.0', dataset, items: data.criteria.map(c => ({
      id: c.id, party_id: c.party_id, program_id: c.program_id, title: c.title,
      text: `${c.description} ${c.test} ${c.reference.quote}`, tags: c.tags, keywords: c.keywords,
      url: `/${dataset}/kriterien/${c.id}/`,
    })) });
    for (const program of data.programs) {
      add(`${prefix}/programs/${program.id}/tree.json`, {
        schema_version: '1.0', dataset, program_id: program.id, tree: program.tree, leaves: program.leaves,
        source: program.source, review: program.review, pdf_url: program.pdf_url ?? null,
        textless_pages: program.textless_pages ?? [], transcription_note: program.transcription_note ?? '',
        criteria_extraction_coverage: extractionCoverage(program, data.criteria),
        markdown: `/api/${prefix}/programs/${program.id}/source.md`,
      });
      add(`${prefix}/programs/${program.id}/source.md`, markdown(program.markdown_path, dataset), 'text/markdown; charset=utf-8');
    }
    for (const law of data.laws) if (law.markdown_path) add(`${prefix}/laws/${law.id}/source.md`, markdown(law.markdown_path, dataset), 'text/markdown; charset=utf-8');
  }
  const sourcesDir = path.join(dataRoot, 'sources');
  if (fs.existsSync(sourcesDir)) for (const file of fs.readdirSync(sourcesDir).filter(f => f.endsWith('.json')).sort()) {
    add(`v1/sources/${file}`, JSON.parse(fs.readFileSync(path.join(sourcesDir, file), 'utf8')));
  }
  for (const schema of fs.readdirSync(path.join(dataRoot, 'schemas')).filter(f => f.endsWith('.json'))) {
    add(`v1/schemas/${schema}`, JSON.parse(fs.readFileSync(path.join(dataRoot, 'schemas', schema), 'utf8')));
  }
  const datasetParameter = { name: 'dataset', in: 'path', required: true, schema: { type: 'string', enum: datasets } };
  const collectionParameter = { name: 'collection', in: 'path', required: true, schema: { type: 'string', enum: collections } };
  const idParameter = { name: 'id', in: 'path', required: true, schema: { type: 'string' } };
  const response = (description: string, type = 'application/json') => ({
    '200': { description, content: { [type]: { schema: { type: type === 'application/json' ? 'object' : 'string' } } } },
    '404': { description: 'No such dataset, collection or record' },
  });
  add('v1/openapi.json', {
    openapi: '3.1.0', info: { title: 'Politrace snapshot API', version: '1.0.0', description: 'Read-only Git-backed snapshots of sources and automated statutory assessments. Queries are not interpreted by the server.' },
    servers: [{ url: '/api' }], paths: {
      '/v1/{dataset}/index.json': { get: { operationId: 'datasetIndex', parameters: [datasetParameter], responses: response('Dataset digest and collection URLs') } },
      '/v1/{dataset}/{collection}.json': { get: { operationId: 'listRecords', parameters: [datasetParameter, collectionParameter], responses: response('{schema_version, dataset, total, items}') } },
      '/v1/{dataset}/{collection}/{id}.json': { get: { operationId: 'getRecord', parameters: [datasetParameter, collectionParameter, idParameter], responses: response('Canonical record') } },
      '/v1/{dataset}/programs/{id}/tree.json': { get: { operationId: 'getTree', parameters: [datasetParameter, idParameter], responses: response('Tree, leaves and citation metadata') } },
      '/v1/{dataset}/{collection}/{id}/source.md': { get: { operationId: 'getMarkdown', parameters: [datasetParameter, { ...collectionParameter, schema: { type: 'string', enum: ['programs', 'laws'] } }, idParameter], responses: response('Verbatim extracted Markdown with PDF page markers', 'text/markdown') } },
      '/v1/{dataset}/stats.json': { get: { operationId: 'getStatistics', parameters: [datasetParameter], responses: response('Statistics by programme and period') } },
      '/v1/{dataset}/search.json': { get: { operationId: 'getSearchIndex', parameters: [datasetParameter], responses: response('Searchable criteria index') } },
      '/v1/{dataset}/coverage.json': { get: { operationId: 'getCoverage', parameters: [datasetParameter], responses: response('Archive counts, source snapshots and explicit remaining law IDs') } },
      '/v1/{dataset}/voting-coverage.json': { get: { operationId: 'getVotingCoverage', parameters: [datasetParameter], responses: response('Per-law parliamentary lookup status, checked dates, unresolved ambiguity and source errors') } },
      '/v1/{dataset}/voting-summary.json': { get: { operationId: 'getVotingSummary', parameters: [datasetParameter], responses: response('Explicit coverage denominators and faction patterns; no party ranking') } },
      '/v1/{dataset}/voting-comparisons.json': { get: { operationId: 'getVotingComparisons', parameters: [datasetParameter], responses: response('Source-linked vote × criterion comparisons; possible tensions, not alleged promise breaches') } },
      '/v1/{dataset}/extraction.json': { get: { operationId: 'getExtractionCoverage', parameters: [datasetParameter], responses: response('Processed and remaining source leaves, for imported programmes only; not human review') } },
      '/v1/{dataset}/readings.json': { get: { operationId: 'getReadingEditions', parameters: [datasetParameter], responses: response('Versioned page-complete OCR reading editions; original evidence unchanged') } },
      '/v1/{dataset}/readings/{id}.json': { get: { operationId: 'getReadingEdition', parameters: [datasetParameter, idParameter], responses: response('OCR page text, original page numbers, provenance and warnings') } },
      '/v1/{dataset}/analysis.json': { get: { operationId: 'getProductionProgress', parameters: [datasetParameter], responses: response('All-party coverage, pending/errors, reported costs and current checkpoint state') } },
      '/v1/{dataset}/analyses.json': { get: { operationId: 'getAnalyses', parameters: [datasetParameter], responses: response('Programme-scoped grouping and pair-level screening audits') } },
      '/v1/{dataset}/experiments.json': { get: { operationId: 'getExperiments', parameters: [datasetParameter], responses: response('Frozen grouping proposals, all-law coverage, pair dispositions and cumulative reported cost') } },
      '/v1/{dataset}/experiments/{id}.json': { get: { operationId: 'getExperiment', parameters: [datasetParameter, idParameter], responses: response('Programme-scoped experiment with all source criteria retained') } },
      '/v1/sources/bundestag-21.json': { get: { operationId: 'getSourceCatalog', responses: response('21st Bundestag scope, programme URLs, PDF hashes and inspection notes') } },
      '/v1/sources/laws-bundestag-21.json': { get: { operationId: 'getArchiveInventory', responses: response('Dated, count-reconciled official archive inventory; not a fresh scan on every run') } },
    },
  });
  add('v1/index.json', { schema_version: '1.0', default_dataset: defaultDataset(), datasets: datasets.map(d => `/api/v1/${d}/index.json`), documentation: '/daten/', openapi: '/api/v1/openapi.json', sources: '/api/v1/sources/bundestag-21.json' });
  add('health.json', { status: 'ok', service: 'politrace-static', schema_version: '1.0' });
  return routes;
};

export const GET: APIRoute = ({ props }) => new Response(
  typeof props.value === 'string' ? props.value : jsonBody(props.value), {
  headers: { 'Content-Type': props.contentType, 'Access-Control-Allow-Origin': '*', 'X-Content-Type-Options': 'nosniff' },
});
