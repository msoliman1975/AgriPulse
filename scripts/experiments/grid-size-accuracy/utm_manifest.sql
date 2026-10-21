SET search_path TO tenant_019eafdc242c7320948e13490efc67dd, public;
SELECT json_agg(blk)
FROM (
  SELECT b.name AS block, b.id::text AS block_id,
         ST_AsGeoJSON(b.boundary_utm)::json AS geometry,
         (SELECT json_agg(d ORDER BY d) FROM (
            SELECT DISTINCT to_char(iij.scene_datetime,'YYYY-MM-DD') AS d
            FROM imagery_ingestion_jobs iij
            WHERE iij.block_id=b.id AND iij.status='succeeded') q) AS dates
  FROM blocks b JOIN farms f ON b.farm_id=f.id
  WHERE f.name='agrosina-suez' AND b.name IN ('AG-R01-C01','AG-R01-C02')
) blk;
