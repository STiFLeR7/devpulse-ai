alter table users enable row level security;
alter table sources enable row level security;
alter table items enable row level security;
alter table item_enriched enable row level security;
alter table automations enable row level security;
alter table user_prefs enable row level security;

-- Backend full access
create policy srv_all_users on users for all to service_role using (true) with check (true);
create policy srv_all_sources on sources for all to service_role using (true) with check (true);
create policy srv_all_items on items for all to service_role using (true) with check (true);
create policy srv_all_enriched on item_enriched for all to service_role using (true) with check (true);
create policy srv_all_auto on automations for all to service_role using (true) with check (true);
create policy srv_all_prefs on user_prefs for all to service_role using (true) with check (true);

-- Public read only on digest
grant select on mv_digest to anon, authenticated;
