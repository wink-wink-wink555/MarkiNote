import { useQueries, useQuery } from '@tanstack/react-query';
import { FileText, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { errorMessage } from '@/shared/api';
import { basename } from '@/shared/lib/format';
import { Modal } from '@/shared/ui/Modal';
import { libraryApi } from '@/features/library/api/libraryApi';
import {
  LibraryTreePicker,
  type LibraryTreeNodeState,
} from '@/features/library/components/LibraryTreePicker';
import {
  directoryItemsToTreeNodes,
  LIBRARY_TREE_ROOT,
  type LibraryTreeNode,
} from '@/features/library/model/libraryTree';

interface Props {
  open: boolean;
  selected: string[];
  reserved?: string[];
  limit: number;
  onChange: (paths: string[]) => void;
  onClose: () => void;
}

const EMPTY_RESERVED: string[] = [];
const TREE_STALE_TIME = 30_000;

export function AttachmentPicker({
  open,
  selected,
  reserved = EMPTY_RESERVED,
  limit,
  onChange,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const reservedPaths = useMemo(() => new Set(reserved), [reserved]);
  const [draft, setDraft] = useState(() => selected.filter((value) => !reservedPaths.has(value)));
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set());
  const incomingSelectionSnapshot = JSON.stringify({ selected, reserved });
  const listing = useQuery({
    queryKey: ['library', ''],
    queryFn: ({ signal }) => libraryApi.list('', signal),
    enabled: open,
    staleTime: TREE_STALE_TIME,
  });
  const selectedPaths = useMemo(() => new Set([...reserved, ...draft]), [draft, reserved]);
  const selectedCount = selectedPaths.size;
  const expandedDirectoryPaths = useMemo(() => [...expandedPaths].sort(), [expandedPaths]);
  const directoryQueries = useQueries({
    queries: expandedDirectoryPaths.map((path) => ({
      queryKey: ['library', path],
      queryFn: ({ signal }: { signal: AbortSignal }) => libraryApi.list(path, signal),
      enabled: open,
      staleTime: TREE_STALE_TIME,
    })),
  });

  useEffect(() => {
    if (!open) return;
    const incoming = JSON.parse(incomingSelectionSnapshot) as { selected: string[]; reserved: string[] };
    const locked = new Set(incoming.reserved);
    setDraft(incoming.selected.filter((value) => !locked.has(value)));
  }, [incomingSelectionSnapshot, open]);
  useEffect(() => {
    if (!open) return;
    setExpandedPaths(new Set());
  }, [open]);

  const nodesByParent = useMemo(() => {
    const nodes = new Map<string, LibraryTreeNode[]>();
    if (listing.data) {
      nodes.set(LIBRARY_TREE_ROOT, directoryItemsToTreeNodes(LIBRARY_TREE_ROOT, listing.data.items));
    }
    directoryQueries.forEach((query, index) => {
      const path = expandedDirectoryPaths[index];
      if (path !== undefined && query.data) {
        nodes.set(path, directoryItemsToTreeNodes(path, query.data.items));
      }
    });
    return nodes;
  }, [directoryQueries, expandedDirectoryPaths, listing.data]);
  const loadingPaths = useMemo(() => {
    const paths = new Set<string>();
    directoryQueries.forEach((query, index) => {
      const path = expandedDirectoryPaths[index];
      if (path !== undefined && query.isPending) paths.add(path);
    });
    return paths;
  }, [directoryQueries, expandedDirectoryPaths]);
  const errorsByPath = useMemo(() => {
    const errors = new Map<string, string>();
    directoryQueries.forEach((query, index) => {
      const path = expandedDirectoryPaths[index];
      if (path !== undefined && query.isError) errors.set(path, errorMessage(query.error));
    });
    return errors;
  }, [directoryQueries, expandedDirectoryPaths]);

  const toggleFile = (itemPath: string) => {
    if (reservedPaths.has(itemPath)) return;
    setDraft((current) => {
      if (current.includes(itemPath)) return current.filter((value) => value !== itemPath);
      if (new Set([...reserved, ...current]).size >= limit) return current;
      return [...current, itemPath];
    });
  };
  const toggleFolder = (folderPath: string) => {
    setExpandedPaths((current) => {
      const next = new Set(current);
      if (next.has(folderPath)) {
        for (const path of next) {
          if (path === folderPath || path.startsWith(`${folderPath}/`)) next.delete(path);
        }
      } else next.add(folderPath);
      return next;
    });
  };
  const nodeState = (node: LibraryTreeNode): LibraryTreeNodeState => {
    if (node.type !== 'file') return {};
    if (reservedPaths.has(node.path)) {
      return {
        disabled: true,
        reason: t('attachmentAlreadyIncluded'),
        note: t('attachmentAlreadyIncluded'),
      };
    }
    if (!selectedPaths.has(node.path) && selectedCount >= limit) {
      const limitReason = t('attachmentLimit', { count: limit });
      return { disabled: true, reason: limitReason, note: limitReason };
    }
    return {};
  };

  return <Modal open={open} title={t('filePicker')} onClose={onClose} size="medium">
    <div className="modal-body attachment-picker">
      <div className="picker-summary">
        <p>{t('attachmentPickerHint')}</p>
        <output aria-live="polite">{t('attachmentSelectionCount', { selected: selectedCount, limit })}</output>
      </div>
      {draft.length > 0 ? <div className="attachment-chips picker-selections" aria-label={t('selectedAttachments')}>
        {draft.map((file) => <span className="attachment-chip" key={file} title={file}>
          <FileText size={13} aria-hidden="true" />
          <span>{basename(file)}</span>
          <button type="button" aria-label={`${t('remove')}: ${file}`} onClick={() => toggleFile(file)}>
            <X size={13} aria-hidden="true" />
          </button>
        </span>)}
      </div> : null}
      <LibraryTreePicker
        label={t('filePicker')}
        nodesByParent={nodesByParent}
        expandedPaths={expandedPaths}
        selectedPaths={selectedPaths}
        selectableType="file"
        multiple
        loadingLabel={t('loading')}
        emptyLabel={t('noFiles')}
        retryLabel={t('retry')}
        loadingPaths={loadingPaths}
        errorsByPath={errorsByPath}
        rootLoading={listing.isPending}
        rootError={listing.isError ? errorMessage(listing.error) : undefined}
        getNodeState={nodeState}
        onToggleFolder={toggleFolder}
        onSelect={(node) => toggleFile(node.path)}
        onRetry={(path) => {
          if (path === LIBRARY_TREE_ROOT) void listing.refetch();
          else {
            const index = expandedDirectoryPaths.indexOf(path);
            if (index >= 0) void directoryQueries[index]?.refetch();
          }
        }}
      />
      {selectedCount >= limit ? <small className="picker-limit" role="status">
        {t('attachmentLimit', { count: limit })}
      </small> : null}
      <div className="modal-actions">
        <button type="button" className="button" onClick={onClose}>{t('cancel')}</button>
        <button type="button" className="button button-primary" onClick={() => {
          onChange(draft);
          onClose();
        }}>{t('confirm')}</button>
      </div>
    </div>
  </Modal>;
}
