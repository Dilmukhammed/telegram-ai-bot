# Graph Memory PR9 — Agent Brief (Documents)

## Status

Implemented (shadow-only, default off):

- package `memory/documents/` — registration, PDF/DOCX structure, region pointers, dereference, normalizer
- `MEMORY_DOCUMENTS_ENABLED=0` by default
- Telegram `on_document` registers durable document sources when enabled
- processor `document_structure_normalizer` / stage `structure_document`
- segment types: `document_root|page|heading|paragraph|table|table_cell|embedded_image`
- embedded images saved as child `photo` workspace sources
- extraction accepts `user_supplied_document` + document segment types
- shadow retrieval document channel is live (lexical over document segments)
- prompt-injection fixtures under `memory/eval/fixtures/documents_v1/`

## Vertical

```text
Telegram PDF/DOCX upload
  -> workspace save
  -> memory source (document / user_supplied_document)
  -> structure_document job
  -> hierarchical segments + document_region pointers
  -> optional candidate_extract
  -> shadow search_documents hits in Memory Context Pack
```

## Config

```text
MEMORY_DOCUMENTS_ENABLED=0
MEMORY_WORKER_ENABLED=1   # required when documents enabled
```

## Tests

```text
python -m unittest test_memory_documents -v
```

## Out of this PR

- standalone photo ingest / OCR / image_region (PR10)
- document_assertion → world-fact promotion policy
- prompt injection into agent (PR13)
- full visual re-inspection of embedded images

## Next

PR10 photos, or continue shadow telemetry review of PR8/PR9.
