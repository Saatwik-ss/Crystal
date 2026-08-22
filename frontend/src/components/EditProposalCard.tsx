import { DiffEditor } from '@monaco-editor/react';
import { useAppStore } from '../store';
import { getMonacoLanguage } from '../utils/language';
import type { ProposedEdit } from '../types';
import { Check, X, Undo2 } from 'lucide-react';
import clsx from 'clsx';

function ValidationBadge({ edit }: { edit: ProposedEdit }) {
  const v = edit.validation;
  if (!v) return null;
  if (v.skipped) {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-600 text-gray-200">
        validation skipped
      </span>
    );
  }
  if (v.ok) {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900 text-emerald-200">
        valid
      </span>
    );
  }
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900 text-red-200">
      invalid
    </span>
  );
}

function FileDiff({ edit }: { edit: ProposedEdit }) {
  const language = getMonacoLanguage(edit.file_path);
  const lineCount = Math.max(
    edit.original.split('\n').length,
    edit.proposed.split('\n').length,
    8
  );
  const height = Math.min(280, Math.max(120, lineCount * 18));

  return (
    <div className="border border-gray-600 rounded overflow-hidden bg-gray-900">
      <div className="flex items-center justify-between gap-2 px-2 py-1.5 bg-gray-700 border-b border-gray-600">
        <div className="min-w-0">
          <p className="text-xs font-mono text-gray-200 truncate" title={edit.file_path}>
            {edit.file_path}
            {edit.is_new_file ? ' (new)' : ''}
          </p>
          {edit.rationale ? (
            <p className="text-[11px] text-gray-400 truncate">{edit.rationale}</p>
          ) : null}
        </div>
        <ValidationBadge edit={edit} />
      </div>
      {!edit.validation?.ok && edit.validation?.errors?.length ? (
        <div className="px-2 py-1 text-[11px] text-red-300 bg-red-950/40 border-b border-gray-700">
          {edit.validation.errors.join('; ')}
        </div>
      ) : null}
      <DiffEditor
        height={height}
        language={language}
        original={edit.original}
        modified={edit.proposed}
        theme="vs-dark"
        options={{
          readOnly: true,
          renderSideBySide: false,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 12,
          lineNumbers: 'on',
          wordWrap: 'on',
        }}
      />
    </div>
  );
}

export default function EditProposalCard() {
  const pendingEdits = useAppStore((s) => s.pendingEdits);
  const lastAppliedRequest = useAppStore((s) => s.lastAppliedRequest);
  const activeRequestId = useAppStore((s) => s.activeRequestId);
  const editApplying = useAppStore((s) => s.editApplying);
  const applyPendingEdits = useAppStore((s) => s.applyPendingEdits);
  const rejectPendingEdits = useAppStore((s) => s.rejectPendingEdits);
  const undoLastApply = useAppStore((s) => s.undoLastApply);

  const showPending = pendingEdits && pendingEdits.length > 0;
  const alreadyOnDisk =
    !!showPending &&
    !!lastAppliedRequest &&
    lastAppliedRequest.request_id === activeRequestId;
  const showUndo = (!showPending && lastAppliedRequest) || alreadyOnDisk;

  if (!showPending && !showUndo) return null;

  const hasInvalid =
    showPending &&
    pendingEdits!.some((e) => e.validation && e.validation.ok === false);

  return (
    <div className="mx-4 mb-3 border border-gray-600 rounded-lg bg-gray-800/80 overflow-hidden">
      <div className="px-3 py-2 border-b border-gray-700 flex items-center justify-between">
        <h4 className="text-sm font-medium text-white">
          {alreadyOnDisk
            ? 'Applied edits'
            : showPending
              ? 'Proposed edits'
              : 'Last applied'}
        </h4>
        {showPending ? (
          <span className="text-[11px] text-gray-400">
            {pendingEdits!.length} file{pendingEdits!.length === 1 ? '' : 's'}
          </span>
        ) : null}
      </div>

      {showPending ? (
        <div className="p-3 space-y-3 max-h-80 overflow-y-auto">
          {pendingEdits!.map((edit) => (
            <FileDiff key={edit.file_path} edit={edit} />
          ))}
        </div>
      ) : (
        <div className="px-3 py-2 text-xs text-gray-400">
          {lastAppliedRequest!.edits.map((e) => e.file_path).join(', ')}
        </div>
      )}

      <div className="px-3 py-2 border-t border-gray-700 flex items-center gap-2">
        {showPending && !alreadyOnDisk ? (
          <>
            <button
              type="button"
              onClick={() => void applyPendingEdits()}
              disabled={editApplying || !!hasInvalid}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors',
                hasInvalid || editApplying
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-emerald-600 hover:bg-emerald-500 text-white'
              )}
              title={hasInvalid ? 'Fix validation errors before applying' : 'Apply all edits'}
            >
              <Check size={14} />
              Apply all
            </button>
            <button
              type="button"
              onClick={rejectPendingEdits}
              disabled={editApplying}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-gray-700 hover:bg-gray-600 text-gray-100 transition-colors disabled:opacity-50"
            >
              <X size={14} />
              Reject
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void undoLastApply()}
              disabled={editApplying}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-amber-700 hover:bg-amber-600 text-white transition-colors disabled:opacity-50"
            >
              <Undo2 size={14} />
              Undo
            </button>
            {alreadyOnDisk ? (
              <button
                type="button"
                onClick={rejectPendingEdits}
                disabled={editApplying}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-gray-700 hover:bg-gray-600 text-gray-100 transition-colors disabled:opacity-50"
              >
                <X size={14} />
                Dismiss
              </button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
