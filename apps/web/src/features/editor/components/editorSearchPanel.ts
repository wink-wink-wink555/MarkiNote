import {
  SearchQuery,
  closeSearchPanel,
  findNext,
  findPrevious,
  getSearchQuery,
  replaceAll,
  replaceNext,
  selectMatches,
  setSearchQuery,
} from '@codemirror/search';
import {
  type EditorView,
  type Panel,
  runScopeHandlers,
  type ViewUpdate,
} from '@codemirror/view';
import type { Text } from '@codemirror/state';

export interface EditorSearchLabels {
  title: string;
  find: string;
  replace: string;
  previous: string;
  next: string;
  selectAll: string;
  matchCase: string;
  regularExpression: string;
  wholeWord: string;
  replaceNext: string;
  replaceAll: string;
  close: string;
  enterQuery: string;
  invalidExpression: string;
  noMatches: string;
  matchTotal: (total: number) => string;
  matchOverflow: (minimum: number) => string;
  matchPosition: (current: number, total: number) => string;
}

interface LabelsRef {
  current: EditorSearchLabels;
}

function actionButton(className: string, text: string): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.textContent = text;
  return button;
}

function field(label: HTMLSpanElement, input: HTMLInputElement): HTMLLabelElement {
  const wrapper = document.createElement('label');
  wrapper.className = 'cm-search-field';
  wrapper.append(label, input);
  return wrapper;
}

function option(input: HTMLInputElement, text: HTMLSpanElement): HTMLLabelElement {
  const wrapper = document.createElement('label');
  wrapper.className = 'cm-search-option';
  wrapper.append(input, text);
  return wrapper;
}

class AccessibleSearchPanel implements Panel {
  readonly dom: HTMLFormElement;
  readonly top = true;

  private query: SearchQuery;
  private readonly searchField = document.createElement('input');
  private readonly replaceField = document.createElement('input');
  private readonly caseField = document.createElement('input');
  private readonly regexpField = document.createElement('input');
  private readonly wordField = document.createElement('input');
  private readonly searchLabel = document.createElement('span');
  private readonly replaceLabel = document.createElement('span');
  private readonly caseLabel = document.createElement('span');
  private readonly regexpLabel = document.createElement('span');
  private readonly wordLabel = document.createElement('span');
  private readonly previousButton = actionButton('cm-search-action cm-search-icon-action', '↑');
  private readonly nextButton = actionButton('cm-search-action cm-search-icon-action', '↓');
  private readonly selectAllButton = actionButton('cm-search-action cm-search-select-all', '');
  private readonly replaceButton = actionButton('cm-search-action', '');
  private readonly replaceAllButton = actionButton('cm-search-action', '');
  private readonly closeButton = actionButton('cm-search-close', '×');
  private readonly status = document.createElement('span');
  private matchCache: {
    doc: Text;
    query: SearchQuery;
    ranges: Array<{ from: number; to: number }>;
    overflow: boolean;
  } | null = null;

  constructor(
    private readonly view: EditorView,
    private readonly labelsRef: LabelsRef,
  ) {
    this.query = getSearchQuery(view.state);
    this.dom = document.createElement('form');
    this.dom.className = 'cm-search cm-search-panel';
    this.dom.noValidate = true;
    this.dom.setAttribute('role', 'search');

    this.searchField.type = 'search';
    this.searchField.className = 'cm-textfield cm-search-input';
    this.searchField.name = 'search';
    this.searchField.autocomplete = 'off';
    this.searchField.spellcheck = false;
    this.searchField.setAttribute('main-field', 'true');
    this.searchLabel.className = 'cm-search-field-label';

    this.replaceField.type = 'text';
    this.replaceField.className = 'cm-textfield cm-replace-input';
    this.replaceField.name = 'replace';
    this.replaceField.autocomplete = 'off';
    this.replaceField.spellcheck = false;
    this.replaceLabel.className = 'cm-search-field-label';

    for (const checkbox of [this.caseField, this.regexpField, this.wordField]) {
      checkbox.type = 'checkbox';
    }

    const mainRow = document.createElement('div');
    mainRow.className = 'cm-search-main-row';
    const navigation = document.createElement('div');
    navigation.className = 'cm-search-navigation';
    navigation.setAttribute('role', 'group');
    navigation.append(this.previousButton, this.nextButton, this.selectAllButton);
    mainRow.append(field(this.searchLabel, this.searchField), navigation, this.closeButton);

    const secondaryRow = document.createElement('div');
    secondaryRow.className = 'cm-search-secondary-row';
    const options = document.createElement('div');
    options.className = 'cm-search-options';
    options.append(
      option(this.caseField, this.caseLabel),
      option(this.regexpField, this.regexpLabel),
      option(this.wordField, this.wordLabel),
    );
    this.status.className = 'cm-search-status';
    this.status.setAttribute('role', 'status');
    this.status.setAttribute('aria-live', 'polite');
    this.status.setAttribute('aria-atomic', 'true');
    secondaryRow.append(options, this.status);
    this.dom.append(mainRow, secondaryRow);

    if (!view.state.readOnly) {
      const replaceRow = document.createElement('div');
      replaceRow.className = 'cm-search-replace-row';
      const replaceActions = document.createElement('div');
      replaceActions.className = 'cm-search-replace-actions';
      replaceActions.append(this.replaceButton, this.replaceAllButton);
      replaceRow.append(field(this.replaceLabel, this.replaceField), replaceActions);
      this.dom.append(replaceRow);
    }

    this.searchField.addEventListener('input', this.commit);
    this.replaceField.addEventListener('input', this.commit);
    this.caseField.addEventListener('change', this.commit);
    this.regexpField.addEventListener('change', this.commit);
    this.wordField.addEventListener('change', this.commit);
    this.previousButton.addEventListener('click', () => findPrevious(view));
    this.nextButton.addEventListener('click', () => findNext(view));
    this.selectAllButton.addEventListener('click', () => selectMatches(view));
    this.replaceButton.addEventListener('click', () => replaceNext(view));
    this.replaceAllButton.addEventListener('click', () => replaceAll(view));
    this.closeButton.addEventListener('click', () => closeSearchPanel(view));
    this.dom.addEventListener('keydown', this.keydown);
    this.dom.addEventListener('submit', (event) => {
      event.preventDefault();
      findNext(view);
    });

    this.setQuery(this.query);
    this.syncLabels();
    this.syncStatus();
  }

  mount(): void {
    this.searchField.focus();
    this.searchField.select();
  }

  update(update: ViewUpdate): void {
    const nextQuery = getSearchQuery(update.state);
    if (!nextQuery.eq(this.query)) this.setQuery(nextQuery);
    this.syncLabels();
    this.syncStatus();
  }

  private readonly commit = () => {
    const query = new SearchQuery({
      search: this.searchField.value,
      replace: this.replaceField.value,
      caseSensitive: this.caseField.checked,
      regexp: this.regexpField.checked,
      wholeWord: this.wordField.checked,
    });
    if (query.eq(this.query)) return;
    this.query = query;
    this.view.dispatch({ effects: setSearchQuery.of(query) });
  };

  private readonly keydown = (event: KeyboardEvent) => {
    if (runScopeHandlers(this.view, event, 'search-panel')) {
      event.preventDefault();
    } else if (event.key === 'Enter' && event.target === this.searchField) {
      event.preventDefault();
      (event.shiftKey ? findPrevious : findNext)(this.view);
    } else if (event.key === 'Enter' && event.target === this.replaceField) {
      event.preventDefault();
      replaceNext(this.view);
    }
  };

  private setQuery(query: SearchQuery): void {
    this.query = query;
    this.searchField.value = query.search;
    this.replaceField.value = query.replace;
    this.caseField.checked = query.caseSensitive;
    this.regexpField.checked = query.regexp;
    this.wordField.checked = query.wholeWord;
  }

  private syncLabels(): void {
    const labels = this.labelsRef.current;
    this.dom.setAttribute('aria-label', labels.title);
    this.searchLabel.textContent = labels.find;
    this.searchField.placeholder = labels.find;
    this.searchField.setAttribute('aria-label', labels.find);
    this.replaceLabel.textContent = labels.replace;
    this.replaceField.placeholder = labels.replace;
    this.replaceField.setAttribute('aria-label', labels.replace);
    this.caseLabel.textContent = labels.matchCase;
    this.regexpLabel.textContent = labels.regularExpression;
    this.wordLabel.textContent = labels.wholeWord;
    this.previousButton.title = labels.previous;
    this.previousButton.setAttribute('aria-label', labels.previous);
    this.nextButton.title = labels.next;
    this.nextButton.setAttribute('aria-label', labels.next);
    this.selectAllButton.textContent = labels.selectAll;
    this.replaceButton.textContent = labels.replaceNext;
    this.replaceAllButton.textContent = labels.replaceAll;
    this.closeButton.title = labels.close;
    this.closeButton.setAttribute('aria-label', labels.close);
  }

  private syncStatus(): void {
    const labels = this.labelsRef.current;
    const invalidExpression = Boolean(this.query.search) && this.query.regexp && !this.query.valid;
    this.searchField.setAttribute('aria-invalid', String(invalidExpression));

    let total = 0;
    let current = 0;
    let overflow = false;
    if (this.query.valid) {
      const selection = this.view.state.selection.main;
      const cache = this.matches();
      total = cache.ranges.length;
      overflow = cache.overflow;
      let low = 0;
      let high = cache.ranges.length - 1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        const range = cache.ranges[middle]!;
        if (range.from === selection.from && range.to === selection.to) {
          current = middle + 1;
          break;
        }
        if (range.from < selection.from || (range.from === selection.from && range.to < selection.to)) low = middle + 1;
        else high = middle - 1;
      }
    }

    if (!this.query.search) this.status.textContent = labels.enterQuery;
    else if (invalidExpression) this.status.textContent = labels.invalidExpression;
    else if (total === 0) this.status.textContent = labels.noMatches;
    else this.status.textContent = current > 0
      ? labels.matchPosition(current, total)
      : overflow ? labels.matchOverflow(total) : labels.matchTotal(total);

    const noUsableMatch = !this.query.valid || total === 0;
    this.previousButton.disabled = noUsableMatch;
    this.nextButton.disabled = noUsableMatch;
    this.selectAllButton.disabled = noUsableMatch;
    this.replaceButton.disabled = noUsableMatch;
    this.replaceAllButton.disabled = noUsableMatch;
  }

  private matches() {
    const doc = this.view.state.doc;
    const cached = this.matchCache;
    if (cached && cached.doc === doc && cached.query.eq(this.query)) return cached;

    const ranges: Array<{ from: number; to: number }> = [];
    let overflow = false;
    if (this.query.valid) {
      const cursor = this.query.getCursor(this.view.state);
      while (ranges.length <= 10_000) {
        const match = cursor.next();
        if (match.done) break;
        if (ranges.length === 10_000) {
          overflow = true;
          break;
        }
        ranges.push({ from: match.value.from, to: match.value.to });
      }
    }
    this.matchCache = { doc, query: this.query, ranges, overflow };
    return this.matchCache;
  }
}

export function createEditorSearchPanel(view: EditorView, labelsRef: LabelsRef): Panel {
  return new AccessibleSearchPanel(view, labelsRef);
}
