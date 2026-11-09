# ADR-004 Ingestion

- Status: accepted
- Date: 2026-11-03

## Context

Drafts quote source text. A quotation that is not in the file is not evidence. Regulatory PDFs are copyrighted and are not committed.

## Decision

PDF via a text-layer library, plus DOCX and XLSX. Store blocks, offsets, and the file hash. No OCR. A missing text layer returns abstain. The full regulatory PDF is gitignored. The committed corpus stores requirement ids, official URLs, and a placeholder for the SHA-256 of a local file that was not hashed in this repo. Short quotations of regulatory text wait until the PDF copyright notice has been read and recorded. That reading is **NOT VERIFIED** here.

## Alternatives

Sending PDFs to a cloud parser exports data and breaks the offline demo.

## Consequences

Tests use synthetic fixtures. An image-only PDF abstains. Kernel code still cannot contain the domain vocabulary from ADR-001.
