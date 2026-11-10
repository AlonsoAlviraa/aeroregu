# S1 latest run

Process date: 2026-11-10. Scorer date field: 2026-11-03.
Generator: s1@1.0.0. Seed label: 20261103.
The seed does not drive a random sampler. The case list is a fixed schedule.

The rates below are ESTIMATE: hits divided by cases in this run, quantized to 0.001.
VERIFIED: this command did not read bench/b1/expert_holdout.
ASSUMPTION: compound complete means the returned fault set equals the injected set.
NOT VERIFIED: this run is not B1, B2, B3, B4, or an expert-authored held-out set.

Cases: 100000 of 100000.
Checker single-fault hits match the case totals: True.
Naive baseline still misses those faults: True.
False alarms on clean cases: 0 / 8000.
False alarms by shift: in_distribution 0/4000, shifted 0/4000.
Abstention by shift: in_distribution 1.000, shifted 1.000.
llm_numeric_violation: 0.
Compound any-hit: 1.000.
Compound complete: 1.000. Wilson 95%: {'low': '1.000', 'high': '1.000', 'method': 'wilson', 'z': '1.96'}.
Compound complete is a pass: True.
ESTIMATE: shifted recall equals in-distribution recall on every scored single fault. This split did not lower the checker.

Per-fault recall is checker_recall. Per-fault false alarms are
false_alarm_by_fault. Per-fault abstention is abstention_by_fault.
Shift intervals and easy/medium/hard recall are in the same file.
Label: ESTIMATE.
