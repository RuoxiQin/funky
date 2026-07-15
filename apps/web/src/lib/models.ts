import type { ModelConfig } from './types'

// True when the worker has an ANTHROPIC_API_KEY (injected by Vite from the root .env). Only
// then does the model picker offer real Claude models; otherwise it tells the user to set
// the key. Falls back to false if the define somehow didn't run (e.g. non-Vite contexts).
export const ANTHROPIC_ENABLED: boolean =
  typeof __ANTHROPIC_ENABLED__ !== 'undefined' ? __ANTHROPIC_ENABLED__ : false

// The Claude models offered when a key is present. Labels are what the UI shows; `model` is
// the API model id. Provider is always anthropic.
export type ModelOption = { label: string; model: string }

export const MODEL_OPTIONS: ModelOption[] = [
  { label: 'Opus 4.8', model: 'claude-opus-4-8' },
  { label: 'Sonnet 5', model: 'claude-sonnet-5' },
]

export const DEFAULT_MODEL_LABEL = MODEL_OPTIONS[0].label

export function modelConfigFor(label: string): ModelConfig {
  const opt = MODEL_OPTIONS.find((m) => m.label === label) ?? MODEL_OPTIONS[0]
  return { provider: 'anthropic', model: opt.model }
}

// Friendly label for a stored agent's model, falling back to the raw id (e.g. agents
// created before this list changed).
export function modelLabel(model: ModelConfig): string {
  return MODEL_OPTIONS.find((m) => m.model === model.model)?.label ?? model.model
}
