SET search_path TO tenant_019eafdc242c7320948e13490efc67dd, public;
COPY (
  SELECT b.name AS block, to_char(a.time,'YYYY-MM-DD') AS date, a.index_code AS index,
         a.mean AS stored_mean, a.std_dev AS stored_std, a.valid_pixel_count AS stored_px
  FROM block_index_aggregates a JOIN blocks b ON a.block_id=b.id
  JOIN farms f ON b.farm_id=f.id
  WHERE f.name='agrosina-suez' AND b.name IN ('AG-R01-C01','AG-R01-C02')
  ORDER BY b.name, a.time, a.index_code
) TO STDOUT WITH CSV HEADER;
