import { CheckCircle2, Circle, Clock3, Play, Trash2 } from 'lucide-react';
import { useAppStore } from '../store';

export default function PlanCard({ onImplement }: { onImplement: () => void }) {
  const plan = useAppStore((s) => s.activePlan);
  const isStreaming = useAppStore((s) => s.isStreaming);
  const setActivePlan = useAppStore((s) => s.setActivePlan);
  const setWorkflowMode = useAppStore((s) => s.setWorkflowMode);

  if (!plan) return null;
  return (
    <section className="mx-4 mb-3 rounded-lg border border-blue-700/70 bg-blue-950/20 overflow-hidden">
      <header className="px-3 py-2 border-b border-blue-900/70">
        <p className="text-xs font-semibold text-blue-200">Implementation plan</p>
        <p className="mt-1 text-xs text-gray-300">{plan.goal || 'Plan the requested change'}</p>
      </header>
      <ol className="px-3 py-2 space-y-2">
        {plan.todos.map((todo) => {
          const Icon = todo.status === 'completed' ? CheckCircle2 : todo.status === 'in_progress' ? Clock3 : Circle;
          return <li key={todo.id} className="flex gap-2 text-xs text-gray-300">
            <Icon size={15} className={todo.status === 'completed' ? 'text-emerald-400 shrink-0' : todo.status === 'in_progress' ? 'text-blue-300 shrink-0' : 'text-gray-500 shrink-0'} />
            <span><span className={todo.status === 'completed' ? 'line-through text-gray-500' : ''}>{todo.title}</span>{todo.note ? <span className="block text-[11px] text-gray-500">{todo.note}</span> : null}</span>
          </li>;
        })}
      </ol>
      <footer className="flex gap-2 px-3 py-2 border-t border-blue-900/70">
        <button type="button" onClick={onImplement} disabled={isStreaming} className="inline-flex items-center gap-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 px-3 py-1.5 text-xs font-medium text-white">
          <Play size={13} /> Implement plan
        </button>
        <button type="button" onClick={() => { setActivePlan(null); setWorkflowMode('chat'); }} disabled={isStreaming} className="inline-flex items-center gap-1.5 rounded bg-gray-700 hover:bg-gray-600 px-3 py-1.5 text-xs text-gray-200">
          <Trash2 size={13} /> Discard
        </button>
      </footer>
    </section>
  );
}
