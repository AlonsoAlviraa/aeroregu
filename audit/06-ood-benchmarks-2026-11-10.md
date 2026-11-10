# OOD third-party benchmarks, 2026-11-10

This is a new audit file.
It does not replace docs/benchmarks/external_public_latest.md.
It does not replace audit/00-resumen.md.

This run does not fill the B1, B2, or B3 expert holdout.
This run does not make B4 ready.
This run does not certify, qualify, or complete the programme.

VERIFIED: UnitSafe, Dronology, JCS, NIST SP 811 Appendix B.8, and QuRE are not in this set.
VERIFIED: Acquired is true. Date 2026-11-10. Command ood-bench.
VERIFIED: Problems ['assurance-case-link', 'calculation-or-unit-fault', 'requirement-quality-defect', 'requirement-to-evidence-trace'].

## CLDR-units

VERIFIED: SHA-256 fa3b509179e5694360ccc777270ac0cae8a042fc32852f0fd2f53e594fc97444. Bytes 46069.
VERIFIED: Source https://raw.githubusercontent.com/unicode-org/cldr/main/common/supplemental/units.xml.
VERIFIED: Licence Unicode-3.0 at https://www.unicode.org/license.txt. Retrieved 2026-11-10.
VERIFIED: Business problem calculation-or-unit-fault.
ASSUMPTION: CLDR is a general unit table, not a rotorcraft calculation note.
VERIFIED: Measured: Exact equality of conversion_interval and the published factor.
NOT VERIFIED: Not measured: Kind-of-quantity. No epsilon. Offset rows are not misses.
VERIFIED: Convert rows 157.
VERIFIED: Exact agreement 74/90. Agree 74. Disagree 16.
VERIFIED: Each disagree is an exact Decimal inequality. No epsilon was applied.
PARTIAL: Unparsed 61. Reason: The unit id did not spell, or conversion_interval returned None. Those rows are not misses.
PARTIAL: Offset rows not scored 2. Reason: offset unit.
VERIFIED: Incompatible 4. Reason: conversion_interval returned incompatible.
VERIFIED: Bad factors 0.
VERIFIED: Compared 90.
VERIFIED: Offset interval none 2.
VERIFIED: Tokens withheld 0.
VERIFIED: Wilson 95 percent low 0.731 high 0.888. Method wilson.
VERIFIED: Disagree arc_minute|revolution pint 0.00004629629629629629629629629631 published 0.00004629629629629629629629629630.
VERIFIED: Disagree arc_second|revolution pint 7.716049382716049382716049385E-7 published 7.716049382716049382716049383E-7.
VERIFIED: Disagree barrel|meter ** 3 pint 0.1192404711960000000000000000 published 0.158987294928.
VERIFIED: Disagree british_thermal_unit|kilogram * meter ** 2 / second ** 2 pint 1055.056 published 1054.350264488888888888888889.
VERIFIED: Disagree dalton|kilogram pint 1.66053906892E-27 published 1.66053878283E-27.
VERIFIED: Disagree electronvolt|kilogram * meter ** 2 / second ** 2 pint 1.602176634E-19 published 1.602177E-19.
VERIFIED: Disagree hertz|revolution / second pint 0.1591549430918953357688837634 published 1.
VERIFIED: Disagree knot|meter / second pint 0.5144444444444444444444444445 published 0.5144444444444444444444444444.
VERIFIED: Disagree parsec|meter pint 30856775814671915.80787161609 published 30856775814913672.59894776383.
VERIFIED: Disagree quart|meter ** 3 pint 0.0009463529459999999999999999999 published 0.000946352946.
VERIFIED: Disagree radian|revolution pint 0.1591549430918953357688837634 published 0.1591549430918953347879019537.
VERIFIED: Disagree rin|meter pint 2.540000000000000000000000000E-29 published 0.00003305785123966942148760330579.
VERIFIED: Disagree rod|meter pint 5.029199999999999999999999999 published 5.02920.
VERIFIED: Disagree slug|kilogram pint 14.59390293720636482939632545 published 14.59390293720636482939632546.
VERIFIED: Disagree steradian|revolution ** 2 pint 0.02533029591058444286096986580 published 0.02533029591058444254871365762.
VERIFIED: Disagree teaspoon|meter ** 3 pint 0.000004928921593750000000000000003 published 0.00000492892159375.
VERIFIED: Incompatible pair decade|year.
VERIFIED: Incompatible pair dram|meter ** 3.
VERIFIED: Incompatible pair pinch|meter ** 3.
VERIFIED: Incompatible pair quarter|year.
PARTIAL: Unparsed pair beaufort|meter / second.
PARTIAL: Unparsed pair british_thermal_unit_it|kilogram * meter ** 2 / second ** 2.
PARTIAL: Unparsed pair bu_jp|meter ** 2.
PARTIAL: Unparsed pair calorie_it|kilogram * meter ** 2 / second ** 2.
PARTIAL: Unparsed pair cho|meter ** 2.
PARTIAL: Unparsed pair cup_imperial|meter ** 3.
PARTIAL: Unparsed pair cup_jp|meter ** 3.
PARTIAL: Unparsed pair cup_metric|meter ** 3.
PARTIAL: Unparsed pair day_person|second.
PARTIAL: Unparsed pair dessert_spoon_imperial|meter ** 3.
PARTIAL: Unparsed pair dessert_spoon|meter ** 3.
PARTIAL: Unparsed pair drop|meter ** 3.
PARTIAL: Unparsed pair dunam|meter ** 2.
PARTIAL: Unparsed pair earth_mass|kilogram.
PARTIAL: Unparsed pair earth_radius|meter.
PARTIAL: Unparsed pair em|em.
PARTIAL: Unparsed pair fluid_ounce_imperial|meter ** 3.
PARTIAL: Unparsed pair fluid_ounce_metric|meter ** 3.
PARTIAL: Unparsed pair foodcalorie|kilogram * meter ** 2 / second ** 2.
PARTIAL: Unparsed pair fun|kilogram.
PARTIAL: Unparsed pair g_force|meter / second ** 2.
PARTIAL: Unparsed pair gallon_imperial|meter ** 3.
PARTIAL: Unparsed pair gasoline_energy_density|kilogram / meter / second ** 2.
PARTIAL: Unparsed pair item|item.
PARTIAL: Unparsed pair jigger|meter ** 3.
PARTIAL: Unparsed pair jo_jp|meter.
PARTIAL: Unparsed pair karat|part.
PARTIAL: Unparsed pair katal|item / second.
PARTIAL: Unparsed pair ken|meter.
PARTIAL: Unparsed pair koku|meter ** 3.
PARTIAL: Unparsed pair kosaji|meter ** 3.
PARTIAL: Unparsed pair light_speed|meter / second.
PARTIAL: Unparsed pair mile_scandinavian|meter.
PARTIAL: Unparsed pair mole|item.
PARTIAL: Unparsed pair month_person|year.
PARTIAL: Unparsed pair night|night.
PARTIAL: Unparsed pair ofglucose|item / kilogram.
PARTIAL: Unparsed pair ofhg|kilogram / meter ** 2 / second ** 2.
PARTIAL: Unparsed pair osaji|meter ** 3.
PARTIAL: Unparsed pair ounce_troy|kilogram.
PARTIAL: Unparsed pair part|part.
PARTIAL: Unparsed pair percent|part.
PARTIAL: Unparsed pair permille|part.
PARTIAL: Unparsed pair permyriad|part.
PARTIAL: Unparsed pair pint_imperial|meter ** 3.
PARTIAL: Unparsed pair pint_metric|meter ** 3.
PARTIAL: Unparsed pair quart_imperial|meter ** 3.
PARTIAL: Unparsed pair ri_jp|meter.
PARTIAL: Unparsed pair sai|meter ** 3.
PARTIAL: Unparsed pair se_jp|meter ** 2.
PARTIAL: Unparsed pair shaku_cloth|meter.
PARTIAL: Unparsed pair shaku_length|meter.
PARTIAL: Unparsed pair shaku|meter ** 3.
PARTIAL: Unparsed pair solar_luminosity|kilogram * meter ** 2 / second ** 3.
PARTIAL: Unparsed pair solar_mass|kilogram.
PARTIAL: Unparsed pair solar_radius|meter.
PARTIAL: Unparsed pair sun|meter.
PARTIAL: Unparsed pair therm_us|kilogram * meter ** 2 / second ** 2.
PARTIAL: Unparsed pair to_jp|meter ** 3.
PARTIAL: Unparsed pair week_person|second.
PARTIAL: Unparsed pair year_person|year.
PARTIAL: Offset pair celsius|kelvin.
PARTIAL: Offset pair fahrenheit|kelvin.

## DOSSPRE-2.0-binary

VERIFIED: SHA-256 ecd542eb0160aa201dfb78bbd7e0acd458e7bc0c7a2efe5f654096332c3ddc86. Bytes 157923.
VERIFIED: Source https://data.mendeley.com/datasets/23xtbvk6yp/2.
VERIFIED: Licence CC-BY-4.0 at https://creativecommons.org/licenses/by/4.0/legalcode. Retrieved 2026-11-10.
VERIFIED: Business problem requirement-quality-defect.
ASSUMPTION: DOSSPRE labels student software requirements, not rotorcraft. The publisher label is security versus non-security.
VERIFIED: Measured: Count of publisher class tokens.
NOT VERIFIED: Not measured: Which class is correct. No classifier exists.
NOT VERIFIED: Scored 0. Missing component: requirement-quality classifier.
VERIFIED: File rows 1316. Class tokens only. Requirement text was not copied.
VERIFIED: Class counts {"NSR": 802, "SR": 514}.
VERIFIED: Requirements copied 0.
PARTIAL: DataCite abstract rows 1317, NSR 801, SR 516. abstract_matches_file is false.

## MobSTr-safetycase

VERIFIED: SHA-256 e2bb673a97fd0dc11dc3e8ecf19f18b288c1bcafb38ed2788d8eb36277d947c3. Bytes 32890.
VERIFIED: Source https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/org.panorama-research.mobstr.safetycase/mobstr-safetycase.integration.
VERIFIED: Licence EPL-2.0 at https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/LICENSE. Retrieved 2026-11-10.
VERIFIED: Business problem assurance-case-link.
VERIFIED: Licence file SHA-256 0becf16567beb77fa252b7664631dd177c8f9a1889e48995b45379c7130e5303.
ASSUMPTION: The MobSTr safety case is automotive, not rotorcraft.
VERIFIED: Measured: Count of argumentation element types.
NOT VERIFIED: Not measured: Whether an asserted link is supported. predict() was not used.
NOT VERIFIED: Scored 0. Missing component: assurance-case linker.
VERIFIED: Argumentation elements 87. Claim text was not copied.
VERIFIED: Element type ArgumentReasoning count 9.
VERIFIED: Element type ArtifactReference count 12.
VERIFIED: Element type AssertedContext count 8.
VERIFIED: Element type AssertedEvidence count 15.
VERIFIED: Element type AssertedInference count 9.
VERIFIED: Element type Claim count 34.

## MobSTr-traces

VERIFIED: SHA-256 eb5398251774b1e2bebc76d38ef5285d39653bff3af3aefc9b13d4c56780059e. Bytes 71719.
VERIFIED: Source https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/__WorkspaceTraceModels/traceModel.xmi.
VERIFIED: Licence EPL-2.0 at https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/LICENSE. Retrieved 2026-11-10.
VERIFIED: Business problem requirement-to-evidence-trace.
VERIFIED: Licence file SHA-256 0becf16567beb77fa252b7664631dd177c8f9a1889e48995b45379c7130e5303.
ASSUMPTION: MobSTr is an automotive trace model, not rotorcraft.
VERIFIED: Measured: predict was called on each trace name. No endpoint pair was a public heading and an evidence id.
NOT VERIFIED: Not measured: Recall against artifact references. A trace retriever. Precision, because there is no negative label.
VERIFIED: Trace elements 174.
VERIFIED: Publisher links 174.
VERIFIED: Predicted links 0.
VERIFIED: Comparable links 0.
VERIFIED: Negative labels 0.
VERIFIED: Precision is null. The file has no negative labels.
NOT VERIFIED: Scored 0. Missing component: publisher labels are artifact references, not the eight public headings. Recall was not computed.
VERIFIED: Trace type AddressedByFMEA count 1.
VERIFIED: Trace type AddressedBySafetyGoal count 5.
VERIFIED: Trace type EffectsComponent count 38.
VERIFIED: Trace type ExpressesAsGoal count 4.
VERIFIED: Trace type HasFailureMode count 41.
VERIFIED: Trace type ImplementsComponent count 17.
VERIFIED: Trace type LeadsToHazard count 35.
VERIFIED: Trace type RelatedTo count 5.
VERIFIED: Trace type SpecifiedByRequirement count 28.

## Refused sources

VERIFIED: figshare-29293868. API licence was cc-by-4.0 on 2026-11-10. The file was not downloaded. The record mixes upstream components whose own licence is not stated.
VERIFIED: zenodo-6524460. API licence id was cc-by-4.0 on 2026-11-10. The zip was not downloaded. It mixes code and data. MobSTr covers the trace problem at a smaller size.
NOT VERIFIED: mendeley-7zbk8zsd8y. A curator note said the source-story licence was unknown. DataCite for this DOI was not opened on 2026-11-10. Not downloaded.
NOT VERIFIED: earlier-register-refusals. CoEST, DSTG/HUMS, ETH Airbus accelerometer, Paderborn, CMAPSS, DASHLINK 644, CWRU, and TPS-CalcBench were not downloaded for this run.

This run does not fill the B1, B2, or B3 expert holdout.
This run does not make B4 ready.
This run does not certify, qualify, or complete the programme.
