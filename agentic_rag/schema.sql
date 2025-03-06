-- Enable the pgvector extension
create extension if not exists vector;

-- Create the documentation chunks table
create table agentic_rag (
    id bigserial primary key,
    source_name varchar not null,
    url varchar not null,
    chunk_number integer not null,
    title varchar not null,
    summary varchar not null,
    content text not null,  -- Added content column
    -- metadata jsonb not null default '{}'::jsonb,  -- Added metadata column
    embedding vector(1536),  -- OpenAI embeddings are 1536 dimensions
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    
    -- Add a unique constraint to prevent duplicate chunks for the same source_name
    unique(url, chunk_number)
);

-- Create an index for better vector similarity search performance
create index on agentic_rag using ivfflat (embedding vector_cosine_ops);

-- Create an index on metadata for faster filtering
-- create index idx_agentic_rag_metadata on agentic_rag using gin (metadata);

-- Create a function to search for documentation chunks
create or replace function match_agentic_rag (
  query_embedding vector(1536),
  source_names varchar(50)[] default NULL,
  urls varchar(200)[] default NULL,
  match_count int default 10
  -- filter jsonb DEFAULT '{}'::jsonb
) returns table (
  id bigint,
  source_name varchar,
  url varchar,
  chunk_number integer,
  title varchar,
  summary varchar,
  content text,
  -- metadata jsonb,
  similarity float
)
language plpgsql
as $$
#variable_conflict use_column
begin
  return query
  select
    id,
    source_name,
    url,
    chunk_number,
    title,
    summary,
    content,
    -- metadata,
    1 - (agentic_rag.embedding <=> query_embedding) as similarity
  from agentic_rag
  where 
    -- where metadata @> filter
    source_names is null or cardinality(source_names) = 0 or source_name = any(source_names)
    or
    urls is null or cardinality(urls) = 0 or url = any(urls)
  order by agentic_rag.embedding <=> query_embedding desc
  limit match_count;
end;
$$;

-- Everything above will work for any PostgreSQL database. The below commands are for Supabase security

-- Enable RLS on the table
alter table agentic_rag enable row level security;

-- Create a policy that allows anyone to read
create policy "Allow public read access"
  on agentic_rag
  for select
  to public
  using (true);