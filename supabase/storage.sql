-- Run once in Supabase SQL Editor as the project owner.
-- Product photos are public. Only trusted server credentials may write objects.
-- No anonymous upload/delete policies are created.
BEGIN;
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
VALUES('product-images','product-images',true,8388608,ARRAY['image/webp'])
ON CONFLICT(id) DO NOTHING;
DO $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM storage.buckets WHERE id='product-images' AND public=true) THEN
    RAISE EXCEPTION 'The existing product-images bucket is private. Inspect it or choose a new bucket; no settings have been overwritten.';
  END IF;
END;
$$;
COMMIT;
