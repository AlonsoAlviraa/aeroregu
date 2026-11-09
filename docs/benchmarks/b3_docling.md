# Docling read of NASA-TM-101040, pages 1–8

Date: 2026-11-03. Command exited 0 after 1163122 ms. Docling 2.146.0. Page range `(1, 8)`.

ESTIMATE, from that one run: 73 text blocks, 13089 characters. The same three dev-gold patterns used by the pypdf scorer matched:

| Field | Gold | Docling text |
| --- | --- | --- |
| blade_count | 3 | 3 |
| gravity | 9.8 | 9.8 |
| strain_gage_count | 31 | 31 |

VERIFIED: those three strings were printed by the run. The local file hash was checked earlier the same day (`5ee682caf7d0ce2f95f327fcb3f9ea2ba5ff7ab25d79f8f4aba08a9a6f79fbed`).

This is not a held-out score. The gold was written with the checker. pypdf on the full memorandum also matched these three fields, so this run does not show Docling ahead of that baseline. A later dev gold has 8 fields. This Docling run was not re-scored against the five fields that sit past page 8. A live single-LLM baseline was not run. `make bench` does not call Docling.
