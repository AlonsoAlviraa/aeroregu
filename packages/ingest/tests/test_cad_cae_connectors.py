from __future__ import annotations

import struct

import pytest
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.router import ingest_bytes

STEP_SAMPLE = b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Synthetic Hub AP242'),'2;1');
FILE_NAME('rotor_hub.stp','2026-11-12T12:00:00',('Eng'),('AeroRegu'),'STEP AP242','','');
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
DATA;
#10=PRODUCT('ROTOR_HUB','ROTOR_HUB','',(#11));
#11=PRODUCT_CONTEXT('',#12,'mechanical');
#12=APPLICATION_CONTEXT('managed model based 3d engineering');
#20=CARTESIAN_POINT('Origin',(0.0,0.0,0.0));
#21=CARTESIAN_POINT('CG_Point',(45.0,-12.0,165.0));
#22=CARTESIAN_POINT('P_Max',(850.0,620.0,420.0));
#23=DATUM('D_A',#20,'A');
#24=FLATNESS_TOLERANCE('FLAT_TOP','Upper flange',#25,#23);
#25=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#26);
#26=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));
#27=POSITION_TOLERANCE('BOLT_POS','M8 hole pattern',#28,#23);
#28=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.15),#26);
#29=(MASS_UNIT()NAMED_UNIT(*)SI_UNIT(.KILO.,.GRAM.));
#30=PROPERTY_DEFINITION('center_of_gravity','CG',#10);
#31=REPRESENTATION('CG_REP',(#21),#99);
#32=PROPERTY_DEFINITION_REPRESENTATION(#30,#31);
#33=MEASURE_REPRESENTATION_ITEM('mass_kg',MASS_MEASURE(950.0),#29);
#34=REPRESENTATION('MASS_REP',(#33),#99);
#35=PROPERTY_DEFINITION('mass','Mass',#10);
#36=PROPERTY_DEFINITION_REPRESENTATION(#35,#34);
#40=DIMENSIONAL_SIZE(#10,'FLANGE_THICKNESS');
#41=TOLERANCE_VALUE(LENGTH_MEASURE(-0.10),LENGTH_MEASURE(0.10));
#42=PLUS_MINUS_TOLERANCE(#41,#40);
ENDSEC;
END-ISO-10303-21;
"""

IGES_SAMPLE = "\n".join(
    [
        f"{'Synthetic IGES 5.3 Bracket':<72}S      1",
        f"{'1H,,1H;,12Hframe_bracket,8Haeroregu,,32,38,6,38,15,,1.0,2,2HMM,1,0.01,':<72}G      1",
        f"{'15H20261112.120000;':<72}G      2",
        "     116       1       0       1       0       0       0       000000000D      1",
        "     116       0       0       1       0                         CG_PT  D      2",
        "     110       2       0       1       0       0       0       000000000D      3",
        "     110       0       0       1       0                         EDGE_1 D      4",
        "     212       3       0       1       0       0       0       000000000D      5",
        "     212       0       0       1       0                         PMI_01 D      6",
        "     406       4       0       1       0       0       0       000000000D      7",
        "     406       0       0       1       0                mass_kg         D      8",
        f"{'116,32.0,14.0,148.0;':<64}{'1':>8}P      1",
        f"{'110,0.0,0.0,0.0,200.0,100.0,50.0;':<64}{'3':>8}P      2",
        f"{'212,1,24HPERP +/-0.05 TO DATUM A ,0.0,0.0,0.0;':<64}{'5':>8}P      3",
        f"{'406,1,910.0;':<64}{'7':>8}P      4",
        f"{'S      1G      2D      8P      4':<72}T      1",
    ]
).encode("ascii")

CATIA_XML_SAMPLE = b"""<CATProduct name="SyntheticEVTOL_Product">
  <Parameters>
    <Parameter name="mass_kg" value="960.0" unit="kg" />
    <Parameter name="thrust_n" value="9800.0" unit="N" />
    <Parameter name="disk_area_m2" value="10.5" unit="m2" />
    <Parameter name="air_density_kg_m3" value="1.225" unit="kg/m3" />
    <Parameter name="figure_of_merit" value="0.72" />
  </Parameters>
  <Relations>
    <Formula
      name="KW_Thrust" target="thrust_n" expression="mass_kg * 9.81"
      value="9417.6" unit="N" />
  </Relations>
  <MassProperties>
    <CenterOfGravity x="0.035" y="-0.008" z="0.172" unit="m" />
  </MassProperties>
  <GDT>
    <Tolerance type="PROFILE_SURFACE" value="0.20" unit="mm" datums="A,B" />
  </GDT>
</CATProduct>
"""

NASTRAN_SAMPLE = b"""$ Synthetic NASTRAN Bulk Data Deck
BEGIN BULK
GRID*   1               0               -1.5-1          -1.2-1
*       0.140
GRID    2       0       0.150   -0.120  0.140
GRID,3,0,0.150,0.120,0.220
GRID,4,0,-0.150,0.120,0.220
CQUAD4,10,1,1,2,3,4
CONM2,20,2,0,920.0,0.025,0.010,0.180
FORCE,30,3,0,1.0,0.0,0.0,4200.0
MOMENT,30,3,0,1.0,0.0,650.0,0.0
PLOAD4,30,10,0.25,0.25,0.35,0.35
ENDDATA
"""

ABAQUS_SAMPLE = b"""*HEADING
Synthetic ABAQUS Lug & Mass Deck
*NODE
1, -0.180, -0.110, 0.120
2,  0.180, -0.110, 0.120
3,  0.180,  0.110, 0.240
4, -0.180,  0.110, 0.240
*ELEMENT, TYPE=C3D4, ELSET=E_LUG
1, 1, 2, 3, 4
*NSET, NSET=LUG_PIN, GENERATE
2, 4, 1
*ELSET, ELSET=MASS_E
1
*MASS, ELSET=MASS_E
880.0
*CLOAD
2, 1, 2800.0
3, 3, 3900.0
*DLOAD
MASS_E, P1, 0.5
*BOUNDARY
1, 1, 3, 0.0
"""


def _build_minimal_ole2_with_stream(stream_name: str, payload: bytes) -> bytes:
    """Build a spec-compliant minimal OLE2 Compound File (sector=512, size >= 4096 uses FAT)."""
    pad_byte = b" " if b"<" in payload else b"\x00"
    padded_payload = payload.ljust(max(4096, ((len(payload) + 511) // 512) * 512), pad_byte)
    stream_size = len(padded_payload)
    data_sectors = stream_size // 512

    # Sector 0: FAT; Sector 1: Directory; Sectors 2..2+N-1: stream
    fat = bytearray(512)
    fat_words = [0xFFFFFFFF] * 128
    fat_words[0] = 0xFFFFFFFD  # FATSECT
    fat_words[1] = 0xFFFFFFFE  # ENDOFCHAIN (directory)
    for i in range(data_sectors):
        sec = 2 + i
        fat_words[sec] = sec + 1 if i + 1 < data_sectors else 0xFFFFFFFE
    struct.pack_into("<128I", fat, 0, *fat_words)

    def _dir_entry(
        name: str,
        obj_type: int,
        child_id: int,
        start_sec: int,
        size: int,
    ) -> bytes:
        enc = name.encode("utf-16-le")[:62] + b"\x00\x00"
        name_len = len(enc)
        enc = enc.ljust(64, b"\x00")
        entry = bytearray(128)
        entry[0:64] = enc
        struct.pack_into("<HBB", entry, 64, name_len, obj_type, 1)
        struct.pack_into("<III", entry, 68, 0xFFFFFFFF, 0xFFFFFFFF, child_id)
        struct.pack_into("<II", entry, 116, start_sec, size)
        return bytes(entry)

    dir_sec = bytearray(512)
    dir_sec[0:128] = _dir_entry("Root Entry", 5, 1, 0xFFFFFFFE, 0)
    dir_sec[128:256] = _dir_entry(stream_name, 2, 0xFFFFFFFF, 2, stream_size)
    for k in range(2, 4):
        dir_sec[k * 128 : (k + 1) * 128] = b"\x00" * 128

    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHH", header, 24, 0x003E, 0x0003, 0xFFFE, 9)
    struct.pack_into("<HI", header, 32, 6, 0)
    struct.pack_into("<II", header, 44, 1, 1)  # num FAT sectors=1, first dir sec=1
    struct.pack_into("<III", header, 56, 4096, 0xFFFFFFFE, 0)
    struct.pack_into("<II", header, 68, 0xFFFFFFFE, 0)
    difat = [0xFFFFFFFF] * 109
    difat[0] = 0
    struct.pack_into("<109I", header, 76, *difat)

    return bytes(header) + bytes(fat) + bytes(dir_sec) + padded_payload


def test_step_ap242_gdt_pmi_and_cg() -> None:
    out = ingest_bytes(STEP_SAMPLE, "rotor_hub.stp")
    assert out["media_type"] == "step_ap242"
    cad = out["cad_cae"]
    assert cad["format"] == "step_ap242"
    assert cad["units"]["length"] == "mm"
    gdt_types = {g["gdt_type"] for g in cad["gdt_pmi"]}
    assert {"FLATNESS_TOLERANCE", "POSITION_TOLERANCE", "PLUS_MINUS_TOLERANCE"} <= gdt_types
    pos = next(g for g in cad["gdt_pmi"] if g["gdt_type"] == "POSITION_TOLERANCE")
    assert pos["tolerance_value"] == "0.15"
    assert pos["datum_refs"] == ["A"]
    assert len(cad["cg_points"]) == 1
    assert cad["cg_points"][0]["coords"] == ["45", "-12", "165"]
    assert any(p["name"] == "mass_kg" and p["value"] == "950" for p in cad["parameters"])


def test_step_invalid_abstains() -> None:
    with pytest.raises(IngestAbstain, match="invalid_step"):
        ingest_bytes(b"not a step file", "broken.stp")


def test_iges_sections_pmi_and_properties() -> None:
    out = ingest_bytes(IGES_SAMPLE, "frame_bracket.igs")
    assert out["media_type"] == "iges"
    cad = out["cad_cae"]
    assert cad["format"] == "iges"
    assert cad["units"]["length"] == "mm"
    assert cad["point_count"] >= 3
    assert any("PERP" in a["text"] for a in cad["annotations"])
    assert any(p["name"] == "mass_kg" and p["value"] == "910" for p in cad["parameters"])


def test_catia_xml_and_xxe_fail_closed() -> None:
    out = ingest_bytes(CATIA_XML_SAMPLE, "evtol_kw.xml")
    assert out["media_type"] == "catia_xml"
    cad = out["cad_cae"]
    assert cad["format"] == "catia_xml"
    assert len(cad["parameters"]) == 5
    assert len(cad["formulas"]) == 1
    assert cad["cg_points"][0]["coords"] == ["0.035", "-0.008", "0.172"]
    assert cad["gdt_pmi"][0]["datum_refs"] == ["A", "B"]

    xxe = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><CATProduct><p>&xxe;</p></CATProduct>'
    with pytest.raises(IngestAbstain, match="invalid_catia_xml"):
        ingest_bytes(xxe, "unsafe.xml")


def test_catia_native_ole2_stream_and_opaque_abstain() -> None:
    ole_with_xml = _build_minimal_ole2_with_stream("KnowledgewareXML", CATIA_XML_SAMPLE)
    out = ingest_bytes(ole_with_xml, "hub.CATPart")
    assert out["media_type"] == "catia_native"
    assert out["cad_cae"]["format"] == "catia_native"
    assert len(out["cad_cae"]["parameters"]) == 5

    opaque_ole = _build_minimal_ole2_with_stream("OpaqueGeomStream", b"\x00\x01\x02\x03binarygeom")
    with pytest.raises(IngestAbstain, match="opaque_catia_binary_no_parameter_stream"):
        ingest_bytes(opaque_ole, "opaque.CATPart")

    with pytest.raises(IngestAbstain, match="invalid_catia_container"):
        ingest_bytes(b"NOT_OLE2_BYTES", "bad.CATProduct")


def test_nastran_bdf_small_large_free_field_and_loads() -> None:
    out = ingest_bytes(NASTRAN_SAMPLE, "wing_rib.bdf")
    assert out["media_type"] == "nastran_bdf"
    cad = out["cad_cae"]
    assert cad["format"] == "nastran_bdf"
    assert cad["mesh"]["node_count"] == 4
    assert cad["mesh"]["element_count"] == 1
    grid1 = next(n for n in cad["mesh"]["nodes"] if n["id"] == "1")
    assert grid1["x"] == "-0.15"
    assert grid1["y"] == "-0.12"
    assert grid1["z"] == "0.14"
    lc0 = cad["loads"]["load_cases"][0]
    assert lc0["sid"] == "30"
    assert lc0["resultant_force_n"] == "4200"
    assert lc0["pload4_count"] == 1
    # CONM2 offset (0.025, 0.010, 0.180) relative to GRID 2 (0.150, -0.120, 0.140)
    assert cad["cg_points"][0]["coords"] == ["0.175", "-0.11", "0.32"]


def test_abaqus_inp_mesh_sets_mass_and_loads() -> None:
    out = ingest_bytes(ABAQUS_SAMPLE, "fuselage_lug.inp")
    assert out["media_type"] == "abaqus_inp"
    cad = out["cad_cae"]
    assert cad["format"] == "abaqus_inp"
    assert cad["mesh"]["node_count"] == 4
    assert cad["mesh"]["element_count"] == 1
    assert cad["mesh"]["nsets"]["LUG_PIN"] == 3
    assert len(cad["masses"]) == 1
    assert cad["masses"][0]["mass"] == "880"
    lc0 = cad["loads"]["load_cases"][0]
    assert lc0["total_force_n"] == ["2800", "0", "3900"]
    assert cad["loads"]["dloads"][0]["load_type"] == "P1"
