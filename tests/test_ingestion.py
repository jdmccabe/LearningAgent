from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from learning_agent.core.documents import load_table_rows
from learning_agent.tasks.rvm.parsing import parse_requirements


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "out" / "test_ingestion"


def test_tsv_requirements_ingestion() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "doors.tsv"
    path.write_text("Object Identifier\tObject Text\nREQ-1\tThe system shall log events.\n", encoding="utf-8")

    requirements = parse_requirements(path)

    assert requirements[0].id == "REQ-1"
    assert "log events" in requirements[0].text
    _clean_scratch()


def test_reqif_ingestion() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    reqif = SCRATCH / "sample.reqif"
    reqif.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<REQ-IF>
  <CORE-CONTENT>
    <REQ-IF-CONTENT>
      <SPEC-OBJECTS>
        <SPEC-OBJECT IDENTIFIER="REQ-2" LONG-NAME="Requirement 2">
          <VALUES>
            <ATTRIBUTE-VALUE-STRING THE-VALUE="The system shall encrypt logs.">
              <DEFINITION><ATTRIBUTE-DEFINITION-STRING-REF>Object Text</ATTRIBUTE-DEFINITION-STRING-REF></DEFINITION>
            </ATTRIBUTE-VALUE-STRING>
          </VALUES>
        </SPEC-OBJECT>
      </SPEC-OBJECTS>
    </REQ-IF-CONTENT>
  </CORE-CONTENT>
</REQ-IF>
""",
        encoding="utf-8",
    )

    requirements = parse_requirements(reqif)

    assert requirements[0].id == "REQ-2"
    assert "encrypt logs" in requirements[0].text
    _clean_scratch()


def test_reqifz_ingestion() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    archive = SCRATCH / "sample.reqifz"
    xml = b"""<REQ-IF><SPEC-OBJECTS><SPEC-OBJECT IDENTIFIER="REQ-3"><VALUES><ATTRIBUTE-VALUE-STRING THE-VALUE="The system shall archive records."><DEFINITION><ATTRIBUTE-DEFINITION-STRING-REF>Object Text</ATTRIBUTE-DEFINITION-STRING-REF></DEFINITION></ATTRIBUTE-VALUE-STRING></VALUES></SPEC-OBJECT></SPEC-OBJECTS></REQ-IF>"""
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("sample.reqif", xml)

    rows = load_table_rows(archive)

    assert rows[0]["id"] == "REQ-3"
    assert "archive records" in rows[0]["object_text"]
    _clean_scratch()


def test_xlsx_requirements_ingestion() -> None:
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "requirements.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Module"
    sheet.append(["Object Identifier", "Object Text"])
    sheet.append(["REQ-4", "The system shall export reports."])
    workbook.save(path)

    requirements = parse_requirements(path)

    assert requirements[0].id == "REQ-4"
    assert "export reports" in requirements[0].text
    _clean_scratch()


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()

