# make bench snapshot

ESTIMATE: written by make bench in one process.

NOT VERIFIED: this file is not an expert-authored held-out result.

B1 ready: False. Cases: 0.
Dev false alarms by fault: all zero. Abstention missing_input 2/2. Same-author dev split. Not the expert holdout.
B2 beats_no_agent: False. beats_single_llm: NOT_VERIFIED.
B2 public headings only: True.
B2 chain llm_numeric_violation: 0. Judge 8/8 Wilson 95%: 0.676 to 1.000. Link recall 6/6 Wilson 95%: 0.610 to 1.000. False-coverage recall 2/2 Wilson 95%: 0.342 to 1.000. False alarms 0/6. Abstentions 0. The span probe is not in these counts.
B2 span probe: verifier links True, chain abstains True. Not in the frozen dev set.
B2 two-pack probe: chain matches verifier True. Not a win. Not in the frozen dev set.
B3 ready: False. dev_pdf_scored: True.
B3 fields: 8/8. Wilson 95%: 0.676 to 1.000.
B3 quote ledger: blade_count 3; gravity 9.8; strain_gage_count 31; flight_condition_count 23; level_flight_ratio_low 0.14; level_flight_ratio_high 0.37; turning_flight_ratio_low 0.26; turning_flight_ratio_high 0.35. llm_numeric_violation: 0.
B3 load-factor column abstained. Value empty. ledger event recorded.
B3 page-limited: 2/8. Wilson 95%: 0.071 to 0.591.
B3 no-agent: 0/8. Wilson 95%: 0.000 to 0.324.
B3 beats_no_agent is true because the no-read baseline scored 0. That comparison is trivial.
B3 false alarms: 0/8. Wilson 95%: 0.000 to 0.324. Page-limited false alarms: 0/2. Abstentions correct: 3/3. Wilson 95%: 0.438 to 1.000. Beating the no-read baseline is trivial.
B3 misses: ["strain_gage_count", "flight_condition_count", "level_flight_ratio_low", "level_flight_ratio_high", "turning_flight_ratio_low", "turning_flight_ratio_high"].
B3 pages: {"blade_count": 2, "gravity": 2, "strain_gage_count": 7, "flight_condition_count": 6, "level_flight_ratio_low": 6, "level_flight_ratio_high": 6, "turning_flight_ratio_low": 6, "turning_flight_ratio_high": 6}.
B3 beats_single_llm: NOT_VERIFIED.
B3 second memorandum: 5/5 full text, 0/5 on the first two pages. Wilson 95%: 0.566 to 1.000. Decimals on the ledger: 4/4. Word label not recomputed: blade_count_word. Ledger events: 4. llm_numeric_violation: 0. Recorded: rotor_radius_m 5.25 m; lift_curve_slope 5.7 1; level_flight_ratio_low 0.14 1; level_flight_ratio_high 0.37 1. Shared flight ids: ['V3101', 'V3103', 'V3105', 'V3106']. Absent: ['V3109', 'V3111']. Flight-table column abstained: True. Unit abstains: 0. No table magnitude stored. Same-session gold. Not a held-out set. False alarms: 0/5. Wilson 95%: 0.000 to 0.434. Page-limited false alarms: 0/0. Abstentions correct: 2/2. Wilson 95%: 0.342 to 1.000. Beating the no-read baseline is trivial.
B4 ready: False.
B4 in-file probe public result: False.
B4 abstain: unit_not_in_file. Sensor range applied: False.
B4 AS365 unit: m/s^2. Records: 3. Structure matches: True. Header step matches 1/8192: True. Duration at 8192 Hz matches 60 s: False. Length abstain: record_length_disagrees. Abstain: limit_not_in_file. Samples were not stored. Not scored.
B4 drill: detector 2/2, naive 1/2, false alarms 0/1 Wilson 95% 0.000 to 0.793. Abstention 1/1 Wilson 95% 0.207 to 1.000. beats_single_llm NOT_VERIFIED. Not a public dataset. B4 is not ready.
Duplicate citation recall: 0/1. Wilson 95%: 0.000 to 0.793. System verdict: abstain.
S1 cases: 100000.
S1 arithmetic: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 bad_citation: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 broken_hash: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 contradictory_requirements: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 false_coverage: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 missing_input: checker 0/0, naive 0/0, Wilson 95% absent.
S1 outside_validity: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 sign: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 stale_revision: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 unit_mismatch: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 unit_scale: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 wrong_input: checker 7000/7000, naive 0/7000, Wilson 95% 0.999 to 1.000.
S1 false-alarm rate: 0.000. Wilson 95%: 0.000 to 0.000.
S1 abstention correctness: 1.000. Wilson 95%: 0.999 to 1.000.
S1 easy: 29000/29000. Wilson 95% 1.000 to 1.000.
S1 medium: 49000/49000. Wilson 95% 1.000 to 1.000.
S1 hard: 22000/22000. Wilson 95% 1.000 to 1.000.
S1 shift: in-distribution equals shifted on every scored fault. This split did not lower the checker.
S1 shift false alarms: in_distribution 0/4000, shifted 0/4000. Abstention: in_distribution 1.000, shifted 1.000.
S1 shifted arithmetic: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted bad_citation: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted broken_hash: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted contradictory_requirements: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted false_coverage: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted outside_validity: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted sign: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted stale_revision: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted unit_mismatch: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted unit_scale: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 shifted wrong_input: 3500/3500. Wilson 95% 0.999 to 1.000.
S1 compound complete: 1.000. Wilson 95%: 1.000 to 1.000.
Programme complete: False. Open legal rows: 5. Signed reviews: 0. Single-LLM known: False. Second gold frozen: True. Drill frozen: True. B1 scored: False. B2 holdout scored: False. B3 holdout scored: False. B3 single-LLM known: False.
