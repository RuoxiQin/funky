// packages/configs/src/envs-types.ts
import type { EgressPolicy, PersistentFs } from "@funky/db/schema";

export type Environment = {
  type: "environment";
  id: string;
  name: string;
  description: string | null;
  metadata: Record<string, string>;
  base_image: string;
  persistent_fs: PersistentFs;
  egress: EgressPolicy;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type CreateEnvInput = {
  id?: string;
  name: string;
  description?: string | null;
  metadata?: Record<string, string>;
  base_image: string;
  persistent_fs?: PersistentFs;
  egress?: EgressPolicy;
};

export type UpdateEnvInput = Partial<Omit<CreateEnvInput, "id">>;
