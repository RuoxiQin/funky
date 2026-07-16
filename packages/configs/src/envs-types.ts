// packages/configs/src/envs-types.ts
import type { NetworkPolicy } from "@funky/db/schema";

export type Environment = {
  type: "environment";
  id: string;
  name: string;
  description: string | null;
  metadata: Record<string, string>;
  network: NetworkPolicy;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type CreateEnvInput = {
  id?: string;
  name: string;
  description?: string | null;
  metadata?: Record<string, string>;
  network?: NetworkPolicy;
};

export type UpdateEnvInput = Partial<Omit<CreateEnvInput, "id">>;
