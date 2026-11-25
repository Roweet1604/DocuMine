-- DocuMine schema. Paste the whole file into the Supabase SQL editor and click Run.
-- Safe to run more than once.

create extension if not exists pgcrypto;

-- ---------- tables ----------

create table if not exists documents (
    id           uuid primary key default gen_random_uuid(),
    filename     text not null,
    file_type    text not null,
    storage_path text not null,
    sha256       text not null unique,
    uploaded_at  timestamptz not null default now()
);

-- chunk ids are increasing numbers, so "order by id" keeps the original file order.
create table if not exists chunks (
    id          bigint generated always as identity primary key,
    document_id uuid not null references documents(id) on delete cascade,
    location    text not null,
    content     text not null,
    tsv         tsvector generated always as (to_tsvector('english', content)) stored
);

create index if not exists chunks_tsv_idx on chunks using gin (tsv);
create index if not exists chunks_document_id_idx on chunks (document_id);

create table if not exists generated_docs (
    id         uuid primary key default gen_random_uuid(),
    doc_type   text not null,
    title      text not null,
    markdown   text not null,
    source_ids jsonb not null default '[]'::jsonb,
    status     text not null default 'draft',
    created_at timestamptz not null default now()
);

-- ---------- row level security ----------
-- RLS on, no policies: the public/anon key can read nothing.
-- The app uses the secret key, which bypasses RLS.

alter table documents      enable row level security;
alter table chunks         enable row level security;
alter table generated_docs enable row level security;

-- ---------- private storage bucket ----------

insert into storage.buckets (id, name, public)
values ('uploads', 'uploads', false)
on conflict (id) do nothing;

-- ---------- search ----------
-- Matches ANY query word (OR) so natural-language questions return results,
-- ranked with ts_rank. Empty or stopword-only queries return no rows.

create or replace function search_chunks(q text, k int default 8)
returns table (
    id          bigint,
    document_id uuid,
    filename    text,
    location    text,
    content     text,
    score       real
)
language plpgsql
stable
set search_path = public
as $$
declare
    and_query tsquery;
    or_query  tsquery;
begin
    if q is null or btrim(q) = '' then
        return;
    end if;

    -- plainto_tsquery stems words and drops stopwords and punctuation safely,
    -- then we swap its AND / phrase operators for OR.
    and_query := plainto_tsquery('english', q);
    if numnode(and_query) = 0 then
        return;
    end if;
    or_query := regexp_replace(and_query::text, '&|<->|<[0-9]+>', '|', 'g')::tsquery;

    return query
    select c.id, c.document_id, d.filename, c.location, c.content,
           ts_rank(c.tsv, or_query) as score
    from chunks c
    join documents d on d.id = c.document_id
    where c.tsv @@ or_query
    order by score desc, c.id
    limit greatest(1, least(coalesce(k, 8), 50));
end;
$$;

-- Only the server (secret key) may call the search function.
revoke execute on function search_chunks(text, int) from public, anon, authenticated;
grant execute on function search_chunks(text, int) to service_role;

-- ---------- vector search (pgvector) ----------
-- Embeddings: gemini-embedding-001, 768 dimensions, cosine distance.
-- Chunks without an embedding still work through keyword search; fill them with
--   python scripts/backfill_embeddings.py

create extension if not exists vector with schema extensions;

alter table chunks add column if not exists embedding extensions.vector(768);

create index if not exists chunks_embedding_idx
    on chunks using hnsw (embedding extensions.vector_cosine_ops);

-- Nearest chunks by cosine distance. score = cosine similarity (1 = identical).
create or replace function match_chunks(query_embedding extensions.vector(768), k int default 8)
returns table (
    id          bigint,
    document_id uuid,
    filename    text,
    location    text,
    content     text,
    score       real
)
language sql
stable
set search_path = public, extensions
as $$
    select c.id, c.document_id, d.filename, c.location, c.content,
           (1 - (c.embedding <=> query_embedding))::real as score
    from chunks c
    join documents d on d.id = c.document_id
    where c.embedding is not null
    order by c.embedding <=> query_embedding, c.id
    limit greatest(1, least(coalesce(k, 8), 50));
$$;

-- Bulk update used by the backfill: items = [{"id": 1, "embedding": "[0.1,0.2,...]"}, ...]
create or replace function set_chunk_embeddings(items jsonb)
returns int
language sql
set search_path = public, extensions
as $$
    with updated as (
        update chunks c
        set embedding = (item->>'embedding')::extensions.vector
        from jsonb_array_elements(items) as item
        where c.id = (item->>'id')::bigint
        returning 1
    )
    select count(*)::int from updated;
$$;

revoke execute on function match_chunks(extensions.vector, int) from public, anon, authenticated;
grant execute on function match_chunks(extensions.vector, int) to service_role;
revoke execute on function set_chunk_embeddings(jsonb) from public, anon, authenticated;
grant execute on function set_chunk_embeddings(jsonb) to service_role;
