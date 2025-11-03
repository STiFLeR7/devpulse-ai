create or replace function refresh_mv_digest()
returns void language plpgsql security definer as $$
begin
    refresh materialized view concurrently mv_digest;
end $$;
