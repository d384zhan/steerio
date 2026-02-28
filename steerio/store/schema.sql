-- Steerio policy store schema
-- Run this in Supabase SQL Editor to create the tables.

create table if not exists judges (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  system_prompt text not null default '',
  knowledge_base text not null default '',
  eval_threshold_chars int not null default 100,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

create table if not exists policies (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  domain      text not null,
  description text not null default '',
  judge_id    uuid references judges(id),
  version     text not null default '1.0',
  active      boolean not null default true,
  escalation_config jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists idx_policies_domain on policies(domain);
