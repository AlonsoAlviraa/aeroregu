# External public benchmarks

Date: 2026-11-09.
ESTIMATE: counts from the pinned files on this machine.
VERIFIED: the SHA-256 pins matched the files that were scored.
The problems and the requirement sentences are not copied here.
This run did not write bench/b1/expert_holdout.

## UnitSafe

Source: https://huggingface.co/datasets/radiativity/UnitSafe
Licence read from the dataset API on 2026-11-09: Apache-2.0.
SHA-256: f7ba395958f70cfb80ff3a2559f9a428dc038cac06d35bf15a71d94f4ce92a8a
Rows: 500. Conversion: 376.
Must-fail dimension_mismatch: 62, scored: 0. On those rows the published signature matches the answer unit on 14, differs on 48, and does not parse on 0. The label is not a unit-versus-signature test.
Must-fail koq_mismatch: 62, scored: 0.
Numeric answers scored: 0.
SciBench-derived rows, prose not copied: 57.
On conversion rows, pint's reading of answer.unit matched the published si_signature on 334 rows, differed on 27, and did not parse on 15.
Agreement among parsed units: 334/361. Wilson 95%: {'low': '0.893', 'high': '0.948', 'method': 'wilson', 'z': '1.96'}.
That comparison uses the published unit token and the published signature. It is not a score of the numeric answer, and it is not B1.
Mismatch unit tokens: {'lm/W': 2, 'lux': 2, 'lm': 2, 'nkat/L': 2, 'kJ/mol': 1, 'rad': 1, 'R': 1, 'G': 1, 'mG': 1, 'Mx': 1, 'mlm': 1, 'fc': 1, 'lm/m²': 1, 'fL': 1, 'cd/m²': 1, 'deg²': 1, 'µkat/L': 1, 'g': 1, 'units/h': 1, 'arcsec': 1, 'arcmin': 1, 'µrad': 1, 'AU': 1}.
Mismatch dimensions: [{'unit': 'AU', 'pint': 'dimensionless', 'published': 'L:1', 'rows': 1}, {'unit': 'G', 'pint': 'T:-1', 'published': 'I:-1,M:1,T:-2', 'rows': 1}, {'unit': 'Mx', 'pint': 'L:1,T:-1', 'published': 'I:-1,L:2,M:1,T:-2', 'rows': 1}, {'unit': 'R', 'pint': 'L:2,M:1,N:-1,T:-2,Θ:-1', 'published': 'I:1,M:-1,T:1', 'rows': 1}, {'unit': 'arcmin', 'pint': 'dimensionless', 'published': 'A:1', 'rows': 1}, {'unit': 'arcsec', 'pint': 'dimensionless', 'published': 'A:1', 'rows': 1}, {'unit': 'cd/m²', 'pint': 'J:1,L:-2', 'published': 'A:1,J:1,L:-2', 'rows': 1}, {'unit': 'deg²', 'pint': 'dimensionless', 'published': 'A:2', 'rows': 1}, {'unit': 'fL', 'pint': 'L:3', 'published': 'A:1,J:1,L:-2', 'rows': 1}, {'unit': 'fc', 'pint': 'L:1,T:-1', 'published': 'A:1,J:1,L:-2', 'rows': 1}, {'unit': 'g', 'pint': 'M:1', 'published': 'L:1,T:-2', 'rows': 1}, {'unit': 'kJ/mol', 'pint': 'L:2,M:1,N:-1,T:-2', 'published': 'L:2,M:1,N:-1,T:-2,Θ:-1', 'rows': 1}, {'unit': 'lm', 'pint': 'J:1', 'published': 'A:1,J:1', 'rows': 2}, {'unit': 'lm/W', 'pint': 'J:1,L:-2,M:-1,T:3', 'published': 'A:1,J:1,L:-2,M:-1,T:3', 'rows': 2}, {'unit': 'lm/m²', 'pint': 'J:1,L:-2', 'published': 'A:1,J:1,L:-2', 'rows': 1}, {'unit': 'lux', 'pint': 'J:1,L:-2', 'published': 'A:1,J:1,L:-2', 'rows': 2}, {'unit': 'mG', 'pint': 'T:-1', 'published': 'I:-1,M:1,T:-2', 'rows': 1}, {'unit': 'mlm', 'pint': 'J:1', 'published': 'A:1,J:1', 'rows': 1}, {'unit': 'nkat/L', 'pint': 'L:-3,N:1,T:-1', 'published': 'N:1,T:-1', 'rows': 2}, {'unit': 'rad', 'pint': 'dimensionless', 'published': 'L:2,T:-2', 'rows': 1}, {'unit': 'units/h', 'pint': 'J:1,L:-2,T:-1', 'published': 'T:-1', 'rows': 1}, {'unit': 'µkat/L', 'pint': 'L:-3,N:1,T:-1', 'published': 'N:1,T:-1', 'rows': 1}, {'unit': 'µrad', 'pint': 'dimensionless', 'published': 'A:1', 'rows': 1}].
Unparsed unit tokens: {'Gy(RBE)': 2, 'mg/kg/dose': 1, 'photons/m²': 1, 'neutrons/(m²·s)': 1, 'kvar': 1, 'm H₂O': 1, 'photons/s': 1, '°F/1000ft': 1, 'IU': 1, 'Osm/kg': 1, 'mOsm/L': 1, 'mEq/h': 1, 'M☉': 1, 'Jy': 1}.

## Dronology

Source: https://huggingface.co/datasets/thearod5/dronology
Licence read from the dataset API on 2026-11-09: MIT.
Artifacts: 796. Traces: 1063.
Gold positive links: 1063.
Predicted links from the existing heading linker: 0.
Linker recall: 0/1063.
Precision: not computed. The trace file has no negative labels.
predict() only links eight public headings, and only next to an ev- id. Dronology identifiers are not those headings. This is that linker on someone else's gold, not a new trace-recovery model.

## JSON canonicalization

Source: https://github.com/cyberphone/json-canonicalization testdata. The LICENSE file, retrieved 2026-11-09, says Apache-2.0. Files with no float matched: ['arrays.json', 'french.json', 'unicode.json', 'weird.json']. Files skipped because they contain a fractional number: ['structures.json', 'values.json']. Mismatches: []. UTF-8 bytes equal to the published outhex image: ['arrays.json', 'french.json', 'unicode.json', 'weird.json']. Byte mismatches: []. The ledger hashes those bytes. This is not a full RFC 8785 pass. Floats stay rejected.

## NIST SP 811 Appendix B.8

Source: the NIST Guide to the SI, Appendix B.8, retrieved 2026-11-09. Rows: 445. No trailing symbol: 103. Symbol unknown to pint: 211. Interval factor agrees: 106. Same symbols, another printed definition: 7. Disagree: 7 [{'pair': 'Btu>J', 'pint': '1055.056', 'published': ['1055.87000', '1059.67000', '1054.80000', '1054.68000']}, {'pair': 'bbl>L', 'pint': '119.2404711960000000000000000', 'published': ['158.987300']}, {'pair': 'kcal>J', 'pint': '4184', 'published': ['4190.02000']}, {'pair': 'lb>kg', 'pint': '0.45359237', 'published': ['0.3732417']}]. Incompatible dimensions: 11. Boldface exact factors were not in the text fetch. This is not B1.

## QuRE

Source: https://zenodo.org/records/16049822. Licence CC BY 4.0. Rows: 2187. Defect: 651. Ok: 1536. Weak-word tokens: 23. On both labels: 21. Only on ok: ['common', 'comparable']. Only on defect: []. Scored: 0. Requirement sentences are not copied. Not B1.

## What this does not close

B1 is still empty. A manufacturer-facing set has to be written by another engineer. This command must not be cited as that set.
