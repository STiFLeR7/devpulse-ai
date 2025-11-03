-- Query performance
create index if not exists idx_items_source on items(source_id);
create index if not exists idx_items_event_time on items(event_time desc);
create index if not exists idx_enriched_score on item_enriched(score desc);
create index if not exists idx_embedding_vector on item_enriched using ivfflat (embedding vector_ops) with (lists = 200);

-- Digest view (public read)
create materialized view if not exists mv_digest as
select
    i.id, i.kind, i.title, i.url, i.event_time,
    e.summary_ai, e.tags, e.score
from items i
join item_enriched e on e.item_id = i.id
where i.status in ('enriched', 'published')
order by e.score desc nulls last, i.event_time desc nulls last;
