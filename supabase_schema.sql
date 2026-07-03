-- Book Review App — one-time database setup.
-- Paste this whole file into Supabase Dashboard → SQL Editor → Run.

create table if not exists public.reviews (
    id uuid primary key,
    template_key text not null,
    title text not null default '',
    author text not null default '',
    pages text not null default '',
    rating numeric(2, 1) not null default 0,
    review_text text not null default '',
    cover_image text,
    aesthetic_images jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Single-user app accessed only with the service role key, so RLS stays
-- enabled with no policies: anon/authenticated keys can read nothing.
alter table public.reviews enable row level security;

-- The 'review-images' storage bucket is created automatically by the app.
