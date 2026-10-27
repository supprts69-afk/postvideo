-- Supabase -> SQL Editor-e ekbar chalao. Notun ekta table, tomar existing table-e kichhu change hoy na.
create table if not exists public.telegram_imports (
  id         bigserial primary key,
  source     text        not null,   -- Telegram chat/channel id
  message_id bigint      not null,
  kind       text        not null,   -- post | video | reel | baseline | skipped:*
  target_id  uuid,                   -- notun toiri content/post id
  created_at timestamptz not null default now(),
  unique (source, message_id)
);

-- Public API (PostgREST) theke keu jeno na dekhe. Direct DB connection-e kono somossha hoy na.
alter table public.telegram_imports enable row level security;
