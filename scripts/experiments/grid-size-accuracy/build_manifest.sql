-- Builds the experiment manifest as a single JSON array (one object per pilot
-- block, each with its UTM boundary + the list of succeeded scenes + raw COG key).
-- Run tuples-only: psql -U postgres -d agripulse -At -f build_manifest.sql
SET search_path TO tenant_019eafdc242c7320948e13490efc67dd, public;

SELECT json_agg(blk)
FROM (
  SELECT
    b.name AS block,
    b.id::text AS block_id,
    b.aoi_hash AS aoi_hash,
    ST_AsGeoJSON(b.boundary_utm)::json AS boundary_utm_geojson,
    (
      SELECT json_agg(s ORDER BY s.scene_datetime)
      FROM (
        SELECT
          iij.scene_id,
          to_char(iij.scene_datetime, 'YYYY-MM-DD"T"HH24:MI:SS') AS date,
          iij.scene_datetime,
          iij.cloud_cover_pct AS cloud_pct,
          (
            SELECT e
            FROM jsonb_array_elements_text(iij.assets_written) e
            WHERE e LIKE '%raw_bands.tif'
            LIMIT 1
          ) AS raw_key
        FROM imagery_ingestion_jobs iij
        WHERE iij.block_id = b.id
          AND iij.status = 'succeeded'
      ) s
    ) AS scenes
  FROM blocks b
  JOIN farms f ON b.farm_id = f.id
  WHERE f.name = 'agrosina-suez'
    AND b.name IN ('AG-R01-C01', 'AG-R01-C02')
) blk;
