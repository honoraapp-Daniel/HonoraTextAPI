-- =====================================================
-- VERIFICATION QUERIES - Run these to confirm migration
-- =====================================================

-- 1. Check all new tables exist
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name IN ('audio_groups', 'tts_segments', 'user_audio_progress', 
                     'chapter_builds', 'paragraph_spans');

-- Expected: 5 rows

-- 2. Check new columns on chapters
SELECT column_name, data_type
FROM information_schema.columns 
WHERE table_name = 'chapters' 
  AND column_name IN ('current_build_id', 'use_paragraph_spans', 'audio_version');

-- Expected: 3 rows

-- 3. Check new columns on tts_segments  
SELECT column_name, data_type
FROM information_schema.columns 
WHERE table_name = 'tts_segments' 
  AND column_name IN ('build_id', 'text_normalized', 'start_char_offset', 'end_char_offset');

-- Expected: 4 rows

-- 4. Check RPC functions exist
SELECT routine_name 
FROM information_schema.routines 
WHERE routine_schema = 'public' 
  AND routine_name IN ('get_chapter_manifest_v3', 'get_group_segments', 
                       'create_chapter_build', 'validate_segment_normalization',
                       'validate_span_coverage', 'validate_no_span_overlaps');

-- Expected: 6 rows
