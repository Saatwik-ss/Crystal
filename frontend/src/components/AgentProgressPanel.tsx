import { useAppStore } from '../store';
import clsx from 'clsx';

export default function AgentProgressPanel() {
  const agentPlan = useAppStore((s) => s.agentPlan);
  const terminalLogs = useAppStore((s) => s.terminalLogs);
  const agentStep = useAppStore((s) => s.agentStep);
  const isStreaming = useAppStore((s) => s.isStreaming);

  const lastTerm = terminalLogs.length
    ? terminalLogs[terminalLogs.length - 1]
    : null;

  if (!agentPlan && !lastTerm && !agentStep) {
    return null;
  }

  return (
    <div className="px-4 pb-2 space-y-2 border-b border-gray-700/80">
      {agentStep && isStreaming ? (
        <p className="text-[11px] text-blue-300/90 font-mono">{agentStep}</p>
      ) : null}

      {agentPlan ? (
        <div className="rounded border border-gray-600 bg-gray-900/60 px-2.5 py-2">
          {agentPlan.goal ? (
            <p className="text-xs text-gray-200 mb-1.5 leading-snug">{agentPlan.goal}</p>
          ) : null}
          <ul className="space-y-1">
            {agentPlan.todos.map((todo) => (
              <li
                key={todo.id}
                className="flex items-start gap-2 text-[11px] text-gray-300"
              >
                <span
                  className={clsx(
                    'mt-0.5 shrink-0 w-3.5 h-3.5 rounded-sm border flex items-center justify-center text-[9px]',
                    todo.status === 'completed' &&
                      'bg-emerald-800 border-emerald-600 text-emerald-100',
                    todo.status === 'in_progress' &&
                      'bg-blue-800 border-blue-500 text-blue-100',
                    todo.status === 'cancelled' &&
                      'bg-gray-700 border-gray-500 text-gray-400 line-through',
                    (todo.status === 'pending' || !todo.status) &&
                      'border-gray-500 text-transparent'
                  )}
                  aria-hidden
                >
                  {todo.status === 'completed'
                    ? '✓'
                    : todo.status === 'in_progress'
                      ? '…'
                      : ''}
                </span>
                <span
                  className={clsx(
                    todo.status === 'cancelled' && 'line-through opacity-60',
                    todo.status === 'completed' && 'opacity-80'
                  )}
                >
                  {todo.title}
                  {todo.note ? (
                    <span className="text-gray-500"> — {todo.note}</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {lastTerm ? (
        <details className="rounded border border-gray-600 bg-gray-950/70 text-[11px]">
          <summary className="cursor-pointer px-2.5 py-1.5 text-gray-300 font-mono truncate list-none flex items-center gap-2">
            <span
              className={clsx(
                'shrink-0',
                lastTerm.returncode === 0 ? 'text-emerald-400' : 'text-red-400'
              )}
            >
              {lastTerm.returncode === 0 ? '✓' : '✗'}
            </span>
            <span className="truncate">{lastTerm.command || 'terminal'}</span>
            {lastTerm.returncode != null ? (
              <span className="text-gray-500 shrink-0">
                exit {lastTerm.returncode}
              </span>
            ) : null}
          </summary>
          <pre className="px-2.5 pb-2 pt-0 max-h-32 overflow-auto text-gray-400 whitespace-pre-wrap break-words border-t border-gray-700">
            {[lastTerm.stdout, lastTerm.stderr, lastTerm.error]
              .filter(Boolean)
              .join('\n')
              .slice(0, 4000) || '(no output)'}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
