import { defaultPageSize, matchingRecords, pageLinks, paginate, parsePage, parsePageSize, progressLabel, topicProgress } from '../lib/criteria-browser';
import { searchText } from '../lib/program-reader-search';
import type { AssessmentStatus } from '../lib/types';

const number = (value: number) => value.toLocaleString('de-DE');

for (const root of document.querySelectorAll<HTMLElement>('[data-filter-root]')) {
  const form = root.querySelector<HTMLFormElement>('[data-filters]');
  if (!form) continue;
  const criteria = root.hasAttribute('data-criteria-browser');
  const controls = [...form.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input[name], select[name]')];
  const records = [...root.querySelectorAll<HTMLElement>('[data-filter-item]')].map(element => ({
    element,
    search: searchText(element.dataset.search || ''),
    topics: (element.dataset.topic || '').split(' ').filter(Boolean),
    parties: (element.dataset.party || '').split(' ').filter(Boolean),
    status: element.dataset.status || '',
    covered: element.dataset.covered === 'true',
  }));
  const sizeSelect = root.querySelector<HTMLSelectElement>('[data-page-size-select]');
  const navigations = [...root.querySelectorAll<HTMLElement>('[data-pagination]')];
  const topicCards = [...root.querySelectorAll<HTMLAnchorElement>('[data-topic-link]')];
  const overview = root.querySelector<HTMLDetailsElement>('[data-topic-overview]');
  const resultsHeading = root.querySelector<HTMLElement>('[data-results-start]');
  let page = 1;
  let pageSize: number = defaultPageSize;

  function filters() {
    const value = (name: string) => controls.find(control => control.name === name)?.value || '';
    return { q: value('q'), topic: value('thema'), party: value('partei'), status: value('status') };
  }

  function active() {
    const panel = root.closest<HTMLElement>('[data-period-panel]');
    if (!panel) return true;
    const year = new URLSearchParams(location.search).get('jahr');
    const panels = [...document.querySelectorAll<HTMLElement>('[data-period-panel]')];
    // Hidden years must not clamp the visible year's URL to their own page count.
    return panels.some(p => p.dataset.periodPanel === year) ? panel.dataset.periodPanel === year : !panel.hidden;
  }

  function currentUrl() {
    const url = new URL(location.href);
    controls.forEach(control => control.value ? url.searchParams.set(control.name, control.value) : url.searchParams.delete(control.name));
    if (criteria) {
      page > 1 ? url.searchParams.set('seite', String(page)) : url.searchParams.delete('seite');
      pageSize !== defaultPageSize ? url.searchParams.set('pro_seite', String(pageSize)) : url.searchParams.delete('pro_seite');
    }
    return url;
  }

  function persist(mode: 'pushState' | 'replaceState', hash?: string) {
    const url = currentUrl();
    if (hash !== undefined) url.hash = hash;
    if (url.href !== location.href) history[mode](null, '', url);
  }

  function showResults() {
    resultsHeading?.focus({ preventScroll: true });
    resultsHeading?.scrollIntoView({ block: 'start' });
  }

  function render() {
    const selected = filters();
    const matches = matchingRecords(records, selected);
    const paging = paginate(matches.length, page, criteria ? pageSize : Math.max(1, records.length));
    page = paging.page;
    const visible = new Set(matches.slice(paging.start, paging.end));
    for (const record of records) record.element.hidden = !visible.has(record);
    const list = root.querySelector<HTMLElement>('[data-filter-list]');
    if (list) list.hidden = matches.length === 0;
    const empty = root.querySelector<HTMLElement>('[data-no-results]');
    if (empty) empty.hidden = matches.length !== 0;
    const count = root.querySelector<HTMLElement>('[data-result-count]');
    if (count) {
      count.textContent = criteria
        ? (matches.length ? `${number(paging.start + 1)}–${number(paging.end)} von ${number(matches.length)} Kriterien${matches.length !== records.length ? ` (${number(records.length)} insgesamt)` : ''}` : `0 von ${number(records.length)} Kriterien`)
        : `${number(matches.length)} von ${number(records.length)} Einträgen`;
    }
    const reset = root.querySelector<HTMLButtonElement>('[data-reset-filters]');
    if (reset) reset.hidden = !Object.values(selected).some(Boolean);
    const pageControls = root.querySelector<HTMLElement>('[data-page-controls]');
    if (pageControls) pageControls.hidden = records.length === 0;
    if (sizeSelect) sizeSelect.value = String(pageSize);

    for (const nav of navigations) {
      nav.hidden = matches.length === 0;
      nav.querySelector<HTMLButtonElement>('[data-page-previous]')!.disabled = page === 1;
      nav.querySelector<HTMLButtonElement>('[data-page-next]')!.disabled = page === paging.pages;
      nav.querySelector<HTMLElement>('[data-page-label]')!.textContent = `Seite ${number(page)} von ${number(paging.pages)}`;
      const links = pageLinks(page, paging.pages).map(value => {
        if (value === 'gap') {
          const gap = document.createElement('span');
          gap.className = 'pagination-gap'; gap.textContent = '…'; gap.setAttribute('aria-hidden', 'true');
          return gap;
        }
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'button pagination-page';
        button.dataset.page = String(value); button.textContent = number(value);
        button.setAttribute('aria-label', `Seite ${number(value)}`);
        if (value === page) button.setAttribute('aria-current', 'page');
        return button;
      });
      nav.querySelector('[data-page-numbers]')!.replaceChildren(...links);
    }

    // Only party (and the enclosing programme year) scopes the progress denominator.
    // A fulfilled-only filter must never turn a topic into "100% implemented".
    const summaries = topicProgress(records.filter(record => !selected.party || record.parties.includes(selected.party)));
    let topicCount = 0;
    for (const card of topicCards) {
      const topic = card.dataset.topicLink!;
      const summary = summaries.get(topic);
      card.hidden = !summary;
      card.classList.toggle('is-selected', selected.topic === topic);
      if (selected.topic === topic) card.setAttribute('aria-current', 'true');
      else card.removeAttribute('aria-current');
      const url = currentUrl();
      url.searchParams.set('thema', topic); url.searchParams.delete('seite');
      url.hash = resultsHeading?.id || '';
      card.href = url.href;
      if (!summary) continue;
      topicCount++;
      card.querySelector('[data-topic-total]')!.textContent = number(summary.total);
      card.querySelector('[data-topic-covered]')!.textContent = number(summary.covered);
      card.querySelector('[data-topic-meter]')!.setAttribute('aria-label', progressLabel(summary));
      card.querySelectorAll<HTMLElement>('[data-topic-status]').forEach(label => {
        label.textContent = number(summary.counts[label.dataset.topicStatus as AssessmentStatus]);
      });
      card.querySelectorAll<HTMLElement>('[data-topic-segment]').forEach(segment => {
        segment.style.flex = String(summary.counts[segment.dataset.topicSegment as AssessmentStatus]);
      });
    }
    const scope = root.querySelector('[data-topic-scope]');
    const partyControl = controls.find(control => control.name === 'partei');
    if (scope && partyControl instanceof HTMLSelectElement) scope.textContent = partyControl.selectedOptions[0].textContent;
    const topicsCount = root.querySelector('[data-topic-count]');
    if (topicsCount) topicsCount.textContent = `${topicCount} ${topicCount === 1 ? 'Thema' : 'Themen'}`;
    const noTopics = root.querySelector<HTMLElement>('[data-no-topics]');
    if (noTopics) noTopics.hidden = topicCount > 0;
    if (resultsHeading) {
      const topicControl = controls.find(control => control.name === 'thema') as HTMLSelectElement;
      resultsHeading.textContent = selected.topic ? `Kriterien: ${topicControl.selectedOptions[0].textContent}` : 'Alle Kriterien';
    }
  }

  function restore() {
    const params = new URLSearchParams(location.search);
    for (const control of controls) {
      const value = params.get(control.name) || '';
      control.value = !(control instanceof HTMLSelectElement) || [...control.options].some(option => option.value === value) ? value : '';
    }
    page = parsePage(params.get('seite'));
    pageSize = parsePageSize(params.get('pro_seite'));
    render();
    if (active()) persist('replaceState');
  }

  function changeFilters(mode: 'pushState' | 'replaceState') {
    page = 1;
    render();
    persist(mode);
  }

  form.addEventListener('submit', event => { event.preventDefault(); changeFilters('replaceState'); });
  form.addEventListener('input', event => {
    if (event.target instanceof HTMLInputElement) changeFilters('replaceState');
  });
  form.addEventListener('change', event => {
    if (event.target instanceof HTMLSelectElement) changeFilters('pushState');
  });
  sizeSelect?.addEventListener('change', () => {
    pageSize = parsePageSize(sizeSelect.value);
    changeFilters('pushState');
  });
  root.querySelector('[data-reset-filters]')?.addEventListener('click', () => {
    controls.forEach(control => control.value = '');
    changeFilters('pushState');
    form.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
  });
  root.addEventListener('click', event => {
    if (!(event.target instanceof Element)) return;
    const target = event.target.closest<HTMLElement>('[data-page], [data-page-previous], [data-page-next], [data-topic-link], [data-show-topics]');
    if (!target || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (target.hasAttribute('data-show-topics')) {
      if (overview) {
        overview.open = true;
        overview.querySelector('summary')?.focus({ preventScroll: true });
        overview.scrollIntoView({ block: 'start' });
      }
      return;
    }
    if (target.hasAttribute('data-topic-link')) {
      controls.find(control => control.name === 'thema')!.value = target.dataset.topicLink!;
      page = 1;
    } else if (target.hasAttribute('data-page-previous')) page--;
    else if (target.hasAttribute('data-page-next')) page++;
    else page = parsePage(target.dataset.page || null);
    render();
    persist('pushState', resultsHeading?.id);
    showResults();
  });
  // Dashboard links use the same controller as pagination and topic cards. Their
  // shareable URLs clear unrelated filters; modified clicks remain ordinary links.
  (root.closest('[data-period-panel]') ?? root).querySelectorAll<HTMLAnchorElement>('[data-criteria-filter]').forEach(link => {
    link.addEventListener('click', event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const url = new URL(link.href);
      if (url.href !== location.href) history.pushState(null, '', url);
      restore();
      showResults();
    });
  });
  window.addEventListener('popstate', restore);
  document.addEventListener('politrace:period-change', restore);
  restore();
}
