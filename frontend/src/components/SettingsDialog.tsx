import { useEffect, useState } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';
import {
  DEFAULT_LLM_SETTINGS,
  type LlmSettings,
} from '../utils/llmSettings';

interface SettingsDialogProps {
  onClose: () => void;
}

export default function SettingsDialog({ onClose }: SettingsDialogProps) {
  const llmSettings = useAppStore((s) => s.llmSettings);
  const setLlmSettings = useAppStore((s) => s.setLlmSettings);
  const [draft, setDraft] = useState<LlmSettings>(llmSettings);
  const [saved, setSaved] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "gemma-7b-it"
  ]);
  
  

  useEffect(() => {
    async function fetchModels() {
      if (!draft.apiKey.trim()) return;
      
      
      try {
        const models = await apiClient.fetchModels(draft.apiKey.trim());
        setAvailableModels(models);
      } catch (e: any) {
        console.error(e);
      } finally {
        
      }
    }
    const timeout = setTimeout(fetchModels, 1000);
    return () => clearTimeout(timeout);
  }, [draft.apiKey]);

  useEffect(() => {
    setDraft(llmSettings);
  }, [llmSettings]);

  const handleSave = () => {
    setLlmSettings({
      apiKey: draft.apiKey.trim(),
      model: draft.model.trim(),
      systemPrompt: draft.systemPrompt.trim(),
    });
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1200);
  };

  const handleReset = () => {
    setDraft({ ...DEFAULT_LLM_SETTINGS });
  };

  const usingDefaults =
    !draft.apiKey.trim() && !draft.model.trim() && !draft.systemPrompt.trim();

  const knownModel = availableModels.some((m) => m === draft.model.trim());
  const modelSelectValue = !draft.model.trim()
    ? ''
    : knownModel
      ? draft.model.trim()
      : '__custom__';

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 w-full max-w-lg mx-4 border border-gray-700 shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Assistant settings</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-sm"
          >
            Close
          </button>
        </div>

        <p className="text-xs text-gray-400 mb-4">
          Leave fields empty to use the server defaults. Your values are stored only in this browser.
        </p>

        <label className="block text-xs text-gray-400 mb-1">API key (Groq or Gemini)</label>
        <input
          type="password"
          autoComplete="off"
          value={draft.apiKey}
          onChange={(e) => setDraft((s) => ({ ...s, apiKey: e.target.value }))}
          placeholder="Leave blank to use the default key"
          className="w-full bg-gray-700 text-white placeholder-gray-500 px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none mb-4"
        />

        <label className="block text-xs text-gray-400 mb-1">Chat model</label>
        <select
          value={modelSelectValue}
          onChange={(e) => {
            const value = e.target.value;
            if (value === '') {
              setDraft((s) => ({ ...s, model: '' }));
            } else if (value === '__custom__') {
              setDraft((s) => ({
                ...s,
                model: knownModel ? '' : s.model,
              }));
            } else {
              setDraft((s) => ({ ...s, model: value }));
            }
          }}
          className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none mb-2"
        >
          <option value="">Server default</option>
          {availableModels.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
          <option value="__custom__">Custom model id…</option>
        </select>

        {modelSelectValue === '__custom__' && (
          <input
            type="text"
            value={draft.model}
            onChange={(e) => setDraft((s) => ({ ...s, model: e.target.value }))}
            placeholder="e.g. llama-3.3-70b-versatile or gemini-2.5-flash"
            className="w-full bg-gray-700 text-white placeholder-gray-500 px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none mb-2"
          />
        )}

        <p className="text-xs text-gray-500 mb-4">
          Use a function-calling chat model (e.g. llama-3.3-70b-versatile,
          gemini-2.5-flash, or openai/gpt-oss-120b). Whisper, TTS, prompt-guard, and
          groq/compound are not supported for Crystal&apos;s local agent tools.
        </p>

        <label className="block text-xs text-gray-400 mb-1">Personal system prompt</label>
        <textarea
          value={draft.systemPrompt}
          onChange={(e) => setDraft((s) => ({ ...s, systemPrompt: e.target.value }))}
          placeholder="Optional instructions added on top of the default assistant prompt"
          rows={6}
          className="w-full bg-gray-700 text-white placeholder-gray-500 px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none mb-3 resize-y"
        />

        <p className="text-xs text-gray-500 mb-4">
          {usingDefaults
            ? 'Using default API key, model, and system prompt.'
            : 'Custom values will be sent with chat and completion requests.'}
        </p>

        <div className="flex justify-between gap-2">
          <button
            onClick={handleReset}
            className="px-4 py-2 rounded bg-gray-700 hover:bg-gray-600 text-white text-sm"
          >
            Clear to defaults
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm"
          >
            {saved ? 'Saved' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
