import {
  CheckCircle2,
  Circle,
  Clock3,
  Play,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '../store';

interface PlanCardProps {
  onImplement: () => void;
}

export default function PlanCard({ onImplement }: PlanCardProps) {
  const plan = useAppStore((state) => state.agentPlan);
  const isStreaming = useAppStore((state) => state.isStreaming);

  if (!plan) {
    return null;
  }

  const discardPlan = () => {
    useAppStore.setState({ agentPlan: null });
  };

  return (
    <section className="mx-4 mb-3 overflow-hidden rounded-lg border border-blue-700/70 bg-blue-950/20">
      <header className="border-b border-blue-900/70 px-3 py-2">
        <p className="text-xs font-semibold text-blue-200">
          Implementation plan
        </p>

        <p className="mt-1 text-xs text-gray-300">
          {plan.goal || 'Plan the requested change'}
        </p>
      </header>

      <ol className="space-y-2 px-3 py-2">
        {plan.todos.map((todo) => {
          const Icon =
            todo.status === 'completed'
              ? CheckCircle2
              : todo.status === 'in_progress'
                ? Clock3
                : Circle;

          const iconClass =
            todo.status === 'completed'
              ? 'text-emerald-400'
              : todo.status === 'in_progress'
                ? 'text-blue-300'
                : 'text-gray-500';

          const titleClass =
            todo.status === 'completed'
              ? 'line-through text-gray-500'
              : 'text-gray-300';

          return (
            <li
              key={todo.id}
              className="flex gap-2 text-xs"
            >
              <Icon
                size={15}
                className={`shrink-0 ${iconClass}`}
              />

              <span>
                <span className={titleClass}>
                  {todo.title}
                </span>

                {todo.note && (
                  <span className="block text-[11px] text-gray-500">
                    {todo.note}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>

      <footer className="flex gap-2 border-t border-blue-900/70 px-3 py-2">
        <button
          type="button"
          onClick={onImplement}
          disabled={isStreaming}
          className="inline-flex items-center gap-1.5 rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:bg-gray-600"
        >
          <Play size={13} />
          Implement plan
        </button>

        <button
          type="button"
          onClick={discardPlan}
          disabled={isStreaming}
          className="inline-flex items-center gap-1.5 rounded bg-gray-700 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-600 disabled:bg-gray-600"
        >
          <Trash2 size={13} />
          Discard
        </button>
      </footer>
    </section>
  );
}
