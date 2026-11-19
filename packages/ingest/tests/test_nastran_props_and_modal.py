from __future__ import annotations

import hashlib
from pathlib import Path

from evidence_ingest.fem_parsers import parse_nastran_bdf, parse_nastran_f06

SAMPLE_BDF_WITH_PROPS = b"""$ UNITS: MM_T_N_MPA
SOL 101
CEND
SUBCASE 1
  LABEL = LIMIT MANEUVER 2.5G
  LOAD = 900
  SPC = 1
SUBCASE 2
  LABEL = ULTIMATE HARD LANDING
  LOAD = 102
  SPC = 1
BEGIN BULK
GRID    1       0       0.0     0.0     0.0
GRID    2       0       1.0     0.0     0.0
CQUAD4  10      100     1       2       2       1
PSHELL  100     1       2.5     1               1
PCOMP   200     0.0     0.0     0.0     STRN    0.0     0.0     SYM
+       2       0.125   0.0     YES     2       0.125   45.0    YES
PBUSH   300     K       1.2+5   1.2+5   5.0+4
MAT1    1       71000.  27000.  0.33    2.78-9
MAT8    2       135000. 9000.   0.30    5000.   0.      0.      1.60-9
FORCE   101     2       0       1000.   0.0     0.0     1.0
GRAV    201     0       9.81    0.0     0.0     -2.5
LOAD    900     1.5     1.0     101     1.0     201
CONM2   50      1       0       100.0   0.20    0.0     0.10
ENDDATA
"""

SAMPLE_F06_SOL103 = (
    b"1    NASTRAN SOL 103 NORMAL MODES\n"
    b"                                  R E A L   E I G E N V A L U E S\n"
    b"   MODE    EXTRACTION      EIGENVALUE           RADIANS             CYCLES\n"
    b"    NO.       ORDER\n"
    b"        1         1        4.489000E+03        6.700000E+01        1.066338E+01\n"
    b"        2         2        6.316547E+03        7.947671E+01        1.264911E+01\n"
    b"        3         3        1.816000E+04        1.347590E+02        2.144757E+01\n"
    b"                     M O D A L   E F F E C T I V E   M A S S   F R A C T I O N\n"
    b"   MODE    FREQ(HZ)     T1            T2            T3\n"
    b"        1  10.66338    0.010         0.005         0.002\n"
    b"        2  12.64911    0.650         0.020         0.010\n"
    b"        3  21.44757    0.020         0.720         0.050\n"
)


def test_parse_nastran_bdf_case_control_properties_sym_grav_load() -> None:
    h = hashlib.sha256(SAMPLE_BDF_WITH_PROPS).hexdigest()
    parsed = parse_nastran_bdf(SAMPLE_BDF_WITH_PROPS, h)

    assert parsed["unit_system"] == "MM_T_N_MPA"
    assert len(parsed["subcases"]) == 2
    assert parsed["subcases"][0]["subcase_id"] == "1"
    assert "LIMIT MANEUVER" in parsed["subcases"][0]["label"]
    assert parsed["subcases"][1]["load_sid"] == "102"

    pshells = parsed["properties"]["pshell"]
    assert len(pshells) == 1
    assert pshells[0]["pid"] == "100"
    assert pshells[0]["thickness"] == "2.5"

    # PCOMP with LAM=SYM doubles plies (2 -> 4) and thickness (0.25 -> 0.50)
    pcomps = parsed["properties"]["pcomp"]
    assert len(pcomps) == 1
    assert pcomps[0]["symmetric"] is True
    assert pcomps[0]["ply_count"] == 4
    assert pcomps[0]["total_thickness"] == "0.5"

    pbushes = parsed["properties"]["pbush"]
    assert len(pbushes) == 1
    assert pbushes[0]["stiffness_k"][:3] == ["120000", "120000", "50000"]

    mat1 = parsed["materials"]["mat1"]
    assert len(mat1) == 1
    assert mat1[0]["e"] == "71000"
    assert mat1[0]["nu"] == "0.33"

    mat8 = parsed["materials"]["mat8"]
    assert len(mat8) == 1
    assert mat8[0]["e1"] == "135000"

    # LOAD 900 = 1.5 * (FORCE_101(0,0,1000) + GRAV_201(0,0,-2.5*9.81*100=-2452.5))
    # => 1.5 * (-1452.5) = -2178.75 N
    lc_900 = next(lc for lc in parsed["loads"]["load_cases"] if lc["sid"] == "900")
    assert lc_900["is_combination"] is True
    assert lc_900["total_force_n"][2] == "-2178.75"
    assert lc_900["resultant_force_n"] == "2178.75"


def test_parse_nastran_bdf_safe_include_and_traversal_block(tmp_path: Path) -> None:
    sub = tmp_path / "props.bdf"
    sub.write_text("PSHELL  101     1       4.2\n", encoding="utf-8")
    outside = tmp_path.parent / "secret_outside.bdf"
    outside.write_text("PSHELL  999     1       9.9\n", encoding="utf-8")

    main_bdf = (
        b"BEGIN BULK\n"
        b"GRID    1       0       0.0     0.0     0.0\n"
        b"INCLUDE 'props.bdf'\n"
        b"INCLUDE '../secret_outside.bdf'\n"
        b"ENDDATA\n"
    )
    parsed = parse_nastran_bdf(main_bdf, hashlib.sha256(main_bdf).hexdigest(), base_dir=tmp_path)
    pids = [p["pid"] for p in parsed["properties"]["pshell"]]
    assert "101" in pids
    assert "999" not in pids


def test_parse_nastran_f06_sol103_modal_eigenvalues_and_eff_mass() -> None:
    h = hashlib.sha256(SAMPLE_F06_SOL103).hexdigest()
    parsed = parse_nastran_f06(SAMPLE_F06_SOL103, h)
    modes = parsed["modal_eigenvalues"]
    assert len(modes) == 3
    assert modes[0]["mode_no"] == "1"
    assert modes[0]["cycles_hz"] == "10.66338"
    assert modes[0]["effective_mass_frac"] == "0.01"
    assert modes[2]["cycles_hz"] == "21.44757"
    assert modes[2]["effective_mass_frac"] == "0.72"
