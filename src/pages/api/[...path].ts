import type { APIRoute, GetStaticPaths } from 'astro';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { dataRoot, datasets, defaultDataset, getData, metrics } from '../../lib/data';

export const prerender = true;

function markdown(relative: string, dataset: string) {
  const resolved = path.resolve(dataRoot, relative);
  const allowed = path.join(dataRoot, dataset) + path.sep;
  if (!resolved.startsWith(allowed) || !resolved.endsWith('.md')) throw new Error('Unsafe Markdown source path');
  return fs.readFileSync(resolved, 'utf8');
}

export const getStaticPaths: GetStaticPaths = () => {
  const routes: { params: { path: string }; props: { body: string; contentType: string } }[] = [];
  const add = (url: string, value: unknown, contentType = 'application/json; charset=utf-8') => routes.push({
    params: { path: url }, props: { body: typeof value === 'string' ? value : JSON.stringify(value, null, 2) + '\n', contentType },
  });
  const collections = ['parties', 'programs', 'criteria', 'laws', 'impacts', 'votes'] as const;
  for (const dataset of datasets) {
    const data = getData(dataset);
    const prefix = `v1/${dataset}`;
    const dataDigest = createHash('sha256').update(JSON.stringify(data)).digest('hex');
    const statistics = data.programs.map(p => ({
      program_id: p.id, party_id: p.party_id, election_year: p.election_year,
      period_start: p.period_start, period_end: p.period_end,
      ...metrics(data.criteria.filter(c => c.program_id === p.id), data.impacts, [p]),
    }));
    add(`${prefix}/index.json`, {
      schema_version: '1.0', dataset, data_sha256: dataDigest,
      disclaimer: dataset === 'demo' ? 'FICTIONAL fixture data. Not actual party programmes, votes or law assessments.' : 'AI links are proposals until explicitly reviewed. Missing evidence is unknown, not failure.',
      collections: Object.fromEntries(collections.map(c => [c, `/api/${prefix}/${c}.json`])),
      statistics: `/api/${prefix}/stats.json`, search: `/api/${prefix}/search.json`,
      filters: 'Static snapshot API. No server-side query parameters. Filter items client-side or use the search index.',
    });
    for (const collection of collections) {
      const items = data[collection];
      add(`${prefix}/${collection}.json`, { schema_version: '1.0', dataset, total: items.length, items });
      for (const item of items) add(`${prefix}/${collection}/${item.id}.json`,
        collection === 'parties' ? { ...item, dataset, programs: data.programs.filter(p => p.party_id === item.id).map(p => p.id), statistics: statistics.filter(s => s.party_id === item.id) } : item);
    }
    add(`${prefix}/stats.json`, {
      schema_version: '1.0', dataset, unit: 'criterion', method: '/methodik/',
      denominator: 'All non-rejected criteria in the programme, including unassessed ones. Null for zero denominator.',
      note: 'Impact scores are ordinal and NOT summed. Only human-reviewed programme + criterion assessments count as fulfilment.',
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
        source: program.source, review: program.review, markdown: `/api/${prefix}/programs/${program.id}/source.md`,
      });
      add(`${prefix}/programs/${program.id}/source.md`, markdown(program.markdown_path, dataset), 'text/markdown; charset=utf-8');
    }
    for (const law of data.laws) if (law.markdown_path) add(`${prefix}/laws/${law.id}/source.md`, markdown(law.markdown_path, dataset), 'text/markdown; charset=utf-8');
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
    openapi: '3.1.0', info: { title: 'Politrace snapshot API', version: '1.0.0', description: 'Read-only Git-backed snapshots. Demo and live are isolated namespaces. Queries are not interpreted by the server.' },
    servers: [{ url: '/api' }], paths: {
      '/v1/{dataset}/index.json': { get: { operationId: 'datasetIndex', parameters: [datasetParameter], responses: response('Dataset digest and collection URLs') } },
      '/v1/{dataset}/{collection}.json': { get: { operationId: 'listRecords', parameters: [datasetParameter, collectionParameter], responses: response('{schema_version, dataset, total, items}') } },
      '/v1/{dataset}/{collection}/{id}.json': { get: { operationId: 'getRecord', parameters: [datasetParameter, collectionParameter, idParameter], responses: response('Canonical record') } },
      '/v1/{dataset}/programs/{id}/tree.json': { get: { operationId: 'getTree', parameters: [datasetParameter, idParameter], responses: response('Tree, leaves and citation metadata') } },
      '/v1/{dataset}/{collection}/{id}/source.md': { get: { operationId: 'getMarkdown', parameters: [datasetParameter, { ...collectionParameter, schema: { type: 'string', enum: ['programs', 'laws'] } }, idParameter], responses: response('Verbatim extracted Markdown with PDF page markers', 'text/markdown') } },
      '/v1/{dataset}/stats.json': { get: { operationId: 'getStatistics', parameters: [datasetParameter], responses: response('Statistics by programme and period') } },
      '/v1/{dataset}/search.json': { get: { operationId: 'getSearchIndex', parameters: [datasetParameter], responses: response('Searchable criteria index') } },
    },
  });
  add('v1/index.json', { schema_version: '1.0', default_dataset: defaultDataset(), datasets: datasets.map(d => `/api/v1/${d}/index.json`), documentation: '/daten/', openapi: '/api/v1/openapi.json' });
  add('health.json', { status: 'ok', service: 'politrace-static', schema_version: '1.0' });
  return routes;
};

export const GET: APIRoute = ({ props }) => new Response(props.body, {
  headers: { 'Content-Type': props.contentType, 'Access-Control-Allow-Origin': '*', 'X-Content-Type-Options': 'nosniff' },
});
