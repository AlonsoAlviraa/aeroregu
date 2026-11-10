# What is measured, and what is not

Date: 2026-11-09. This file separates own measurements, external measurements, and checks that are still empty.

Own data means this repository generated the cases and the checker knows the injector. External data means someone else published the file. The blind set does not exist yet. UnitSafe, Dronology, and QuRE do not fill it.

## Own data

| Check | Result on 2026-11-09 | Label |
| --- | --- | --- |
| S1, 100000 synthetic notes | Single faults 7000/7000. The seed label does not sample. The generator and the checker are the same package | ESTIMATE. Not an external validation |
| `bench/dev` and `bench/holdout` | Written by the fault injector | Smoke only |
| B2 development, 8 reports | The chain ties the verifier at 8/8. Eight headings only | ESTIMATE |
| B3 NASA memoranda | Same-session gold. `ready` is false | ESTIMATE |
| B4 | Not scored | NOT VERIFIED |

## External files opened on 2026-11-09

| Source | What was checked | Score against this code | Still not scored |
| --- | --- | --- | --- |
| UnitSafe, Apache-2.0, SHA-256 `f7ba395958f70cfb80ff3a2559f9a428dc038cac06d35bf15a71d94f4ce92a8a`, 500 rows | `answer.unit` dimensions against `si_signature` on 376 conversion rows | 334 match, 27 differ, 15 do not parse. Parsed agreement 334/361. Wilson 95% 0.893 to 0.948. The 27 differences list pint exponents and the published signature in `external_public_latest.json` | 376 numeric answers. 62 dimension-mismatch rows are not scored: the published signature matches the answer unit on 14 and differs on 48, so the label is not a unit-versus-signature test. 62 kind-of-quantity rows are not scored: the signature matches on 47, differs on 9, and does not parse on 6. This checker has no kind-of-quantity verdict |
| Dronology mirror `thearod5/dronology`, MIT, 796 artifacts, 1063 positive traces | The eight-heading linker | 0/1063. No negative labels, so no precision | A trace retriever. MobSTr was not cloned |
| QuRE v1.0.1, CC BY 4.0, Zenodo 10.5281/zenodo.16049822 | File size 332428 matches the API. SHA-256 `c6a0c872873ba54028b97361c4cf1d5ad488bdea622a922cbee33265814925d6`. 2187 rows, 2111 distinct requirement strings, 651 `defect`, 1536 `ok`. Every row has one of 23 `weak_word` tokens. 21 of those tokens appear on both labels. `common` and `comparable` appear only on `ok` | Not scored. No requirement-quality checker reads this file. The requirement text is not copied. The token is not the defect label | The 651 defect labels |
| AeroGround `tpattanayak/aeroground` | API on 2026-11-09: `license` other, `license_name` mixed-publicdomain-llama3-ccby. `stats.json`: 7977 verified-gold rows, 1173 abstention rows, 8815 retrieval queries. DPO split sums to 9988 | Not downloaded and not scored. No FAA question answerer | Abstention and citation accuracy |
| MobSTr `panorama-research/mobstr-dataset` | GitHub API on 2026-11-09: SPDX EPL-2.0. Last push 2022-03-18 | Not cloned and not scored | Requirement-to-safety-case links |
| CoEST index `http://sarec.nd.edu/coest/datasets/` | The index opened on 2026-11-09 and listed 15 zip files, including CM1-NASA.zip | Not downloaded. The index states no licence | Trace matrices |
| JCS testdata, Anders Rundgren, RFC 8785. The LICENSE file says Apache-2.0. The GitHub API SPDX field was NOASSERTION | Six published input/output pairs, plus the outhex byte images, under `data/external/jcs` | `arrays`, `french`, `unicode`, and `weird` match as text and as UTF-8 bytes. `structures` and `values` contain a fractional number and were not scored | Full RFC 8785 number canonicalization. This canonicalizer rejects floats. The ledger hashes the bytes that matched |
| NIST SP 811 Appendix B.8, retrieved 2026-11-09. US government table. Exact-factor boldface was not in the text fetch | 445 printed conversion rows. A row is scored only when both cells end in a unit symbol pint accepts | Interval factors: 106 agree within half the last printed digit. 7 share the symbols of another row that does agree. 7 disagree. 11 are dimensionally incompatible. The rest have no usable symbol | B1 calculation notes. The disagreeing symbols are listed in `external_public_latest.md` |

## Waiting for another engineer

| Benchmark | State | What closes it |
| --- | --- | --- |
| B1 | 0 cases. A secondary page (IDEA Statica) quotes a Chinese combined shear-and-tension check as the square root of two squared force ratios. A third-party checklist describes an AISC check as the sum of two squared stress ratios. Those pages are not the standards. No numerical worked example was copied. A generated search summary is not a source | Cases in `B1_EXPERT_DIR`, then `score-blind-b1` |
| B2 | 0 cases | Cases in `B2_EXPERT_DIR`, then `score-blind-b2` |
| B3 | 0 cases | A document that is not one of the two development NASA files, then `score-blind-b3` |
| B4 | Not ready | A public series whose licence and unit are verified, with the limit written down before the first count |
| Kind-of-quantity refusal | No verdict in the checker | A component that does not exist yet, then an external set |
| Single-LLM baseline | Not run | A live model call, still forbidden from inventing a physical number |

The procedure for the first three rows is `docs/benchmarks/blind_holdout_protocol.md`.
