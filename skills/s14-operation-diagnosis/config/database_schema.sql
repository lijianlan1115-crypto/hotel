-- S14 minimum database contract.
-- OpenClaw should provide these normalized fields for S14 to read directly.
-- Other jobs may write this table, but S14 must not receive their output as
-- runtime input parameters.

create table if not exists s14_operating_metrics (
  id integer primary key,
  hotel_id varchar(64) not null,
  platform varchar(32) not null,
  data_date date not null,
  time_grain varchar(16) default 'daily',
  period_start_date date,
  period_end_date date,

  hotel_name varchar(128),
  channel_source varchar(32),

  revpar decimal(12, 2),
  adr decimal(12, 2),
  occupancy decimal(8, 4),
  room_revenue decimal(14, 2),
  sold_room_nights decimal(12, 2),
  available_room_nights decimal(12, 2),

  exposure decimal(14, 2),
  views decimal(14, 2),
  peer_rank decimal(8, 4),
  booking_conversion_rate decimal(8, 4),
  payment_conversion_rate decimal(8, 4),
  lost_orders decimal(12, 2),
  lost_amount decimal(14, 2),

  price_completeness decimal(8, 4),
  inventory_health_rate decimal(8, 4),
  room_type_health_rate decimal(8, 4),

  promo_amount decimal(14, 2),
  promo_cost decimal(14, 2),
  promo_roi decimal(12, 4),
  promo_detail_ready boolean default false,

  image_quality_rating varchar(16),
  video_status varchar(16),
  room_selling_point_status varchar(16),
  entry_tag_quality varchar(16),

  rating_total decimal(8, 4),
  bad_review_rate decimal(8, 4),
  unreplied_reviews decimal(12, 2),

  completed_actions text,
  pending_actions text,
  review_reason text,
  field_completeness decimal(8, 4),

  created_at timestamp default current_timestamp
);

create index if not exists idx_s14_operating_metrics_lookup
  on s14_operating_metrics (hotel_id, platform, data_date);
