-- =====================================================================
-- NOTUN / FAKA Supabase project-e worker TEST korar jonno.
-- SQL Editor-e ekbar puro file chalao (ei file-ei telegram_imports-o ache,
-- tai schema.sql alada chalate hobe na).
-- Tomar ashol website-er table-er moto-i column/constraint, shudhu worker ja chhuy tai.
-- Ashol (existing) project-e eta chalaio na, otay already ei table gulo ache.
-- =====================================================================
create extension if not exists citext;

create or replace function public.set_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at = now(); return new; end $$;

-- ---------- profiles (author) ----------
create table if not exists public.profiles (
  id           uuid primary key default gen_random_uuid(),
  username     text unique,
  display_name text,
  created_at   timestamptz not null default now()
);

create table if not exists public.categories (
  id         uuid primary key default gen_random_uuid(),
  name       text,
  created_at timestamptz not null default now()
);

-- ---------- tags ----------
create table if not exists public.tags (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  slug       citext not null unique,
  status     text not null default 'active' check (status in ('active','inactive')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------- content (video / reel) ----------
create table if not exists public.content (
  id               uuid primary key default gen_random_uuid(),
  owner_id         uuid not null references public.profiles(id) on delete cascade,
  title            text not null,
  slug             citext not null unique,
  description      text,
  content_type     text not null default 'video' check (content_type in ('video','photo','link')),
  category_id      uuid references public.categories(id) on delete set null,
  thumbnail_url    text,
  media_url        text,
  source           text not null default 'external' check (source in ('external','upload')),
  duration_seconds integer,
  visibility       text not null default 'public' check (visibility in ('public','unlisted','private','scheduled')),
  status           text not null default 'published' check (status in ('draft','pending','published','rejected')),
  is_premium       boolean not null default false,
  price_gems       integer,
  allow_comments   boolean not null default true,
  views            bigint not null default 0,
  scheduled_at     timestamptz,
  published_at     timestamptz default now(),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  is_short         boolean not null default false,
  allow_download   boolean not null default false
);

create table if not exists public.content_tags (
  content_id uuid not null references public.content(id) on delete cascade,
  tag_id     uuid not null references public.tags(id) on delete cascade,
  primary key (content_id, tag_id)
);

-- ---------- posts (text / photo / link) ----------
create table if not exists public.posts (
  id         uuid primary key default gen_random_uuid(),
  author_id  uuid not null references public.profiles(id) on delete cascade,
  title      text,
  body       text,
  video_url  text,
  images     jsonb not null default '[]'::jsonb,
  repost_of  uuid references public.posts(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------- worker-er dedup/state table ----------
create table if not exists public.telegram_imports (
  id         bigserial primary key,
  source     text   not null,
  message_id bigint not null,
  kind       text   not null,
  target_id  uuid,
  created_at timestamptz not null default now(),
  unique (source, message_id)
);

-- ---------- updated_at triggers ----------
drop trigger if exists trg_tags_updated_at    on public.tags;
create trigger trg_tags_updated_at    before update on public.tags    for each row execute function public.set_updated_at();
drop trigger if exists trg_content_updated_at on public.content;
create trigger trg_content_updated_at before update on public.content for each row execute function public.set_updated_at();
drop trigger if exists trg_posts_updated_at   on public.posts;
create trigger trg_posts_updated_at   before update on public.posts   for each row execute function public.set_updated_at();

-- ---------- RLS on (policy nai): public API theke keu dekhbe na.
-- Worker direct DB + service role key use kore, tai bypass hoy. Table Editor-e tumi dekhte parbe.
alter table public.profiles         enable row level security;
alter table public.categories       enable row level security;
alter table public.tags             enable row level security;
alter table public.content          enable row level security;
alter table public.content_tags     enable row level security;
alter table public.posts            enable row level security;
alter table public.telegram_imports enable row level security;

-- ---------- public bucket "media" ----------
insert into storage.buckets (id, name, public)
values ('media', 'media', true)
on conflict (id) do update set public = true;

-- ---------- test author ----------
insert into public.profiles (username, display_name)
values ('tg_test', 'Telegram Test')
on conflict (username) do nothing;

-- Shesh query-r result-e author_id dekhabe. Oi "id" copy kore TG_SOURCES-er author_id-te dao.
select id as author_id, username from public.profiles where username = 'tg_test';
