export interface LlmSettings {
  apiKey: string;
  model: string;
  systemPrompt: string;
}

/** Chat-capable models shown in Settings (not Whisper/TTS/guard). */
export const CHAT_MODEL_OPTIONS = [
  'llama-3.3-70b-versatile',
  'llama-3.1-8b-instant',
  'gemini-2.5-flash',
  'gemini-2.5-pro',
  'gemini-2.0-flash',
  'gemini-1.5-flash',
  'gemini-1.5-pro',
  'openai/gpt-oss-120b',
  'openai/gpt-oss-20b',
  'meta-llama/llama-4-scout-17b-16e-instruct',
  'meta-llama/llama-4-maverick-17b-128e-instruct',
  'qwen/qwen3-32b',
  'moonshotai/kimi-k2-instruct',
] as const;

export const DEFAULT_LLM_SETTINGS: LlmSettings = {
  apiKey: '',
  model: '',
  systemPrompt: '',
};

const STORAGE_KEY = 'crystal.llmSettings';

const NON_CHAT_HINTS = ['whisper', 'orpheus', 'prompt-guard', 'compound'];

export function isChatModel(model: string): boolean {
  const name = model.trim().toLowerCase();
  if (!name) return true;
  return !NON_CHAT_HINTS.some((hint) => name.includes(hint));
}

export function loadLlmSettings(): LlmSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_LLM_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<LlmSettings>;
    const model = typeof parsed.model === 'string' ? parsed.model : '';
    return {
      apiKey: typeof parsed.apiKey === 'string' ? parsed.apiKey : '',
      // Drop invalid models saved from earlier free-text settings
      model: isChatModel(model) ? model : '',
      systemPrompt: typeof parsed.systemPrompt === 'string' ? parsed.systemPrompt : '',
    };
  } catch {
    return { ...DEFAULT_LLM_SETTINGS };
  }
}

export function saveLlmSettings(settings: LlmSettings): void {
  const cleaned: LlmSettings = {
    ...settings,
    model: isChatModel(settings.model) ? settings.model.trim() : '',
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cleaned));
}

export function llmPayload(settings: LlmSettings): {
  api_key?: string;
  model?: string;
  system_prompt?: string;
} {
  const payload: { api_key?: string; model?: string; system_prompt?: string } = {};
  const apiKey = settings.apiKey.trim();
  const model = settings.model.trim();
  const systemPrompt = settings.systemPrompt.trim();
  if (apiKey) payload.api_key = apiKey;
  if (model && isChatModel(model)) payload.model = model;
  if (systemPrompt) payload.system_prompt = systemPrompt;
  return payload;
}
