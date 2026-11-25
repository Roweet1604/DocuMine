"""Rebuilds the binary sample files: python sample_data/make_samples.py

- kestrel_incident_INC-007.docx  (incident record, with tables)
- kestrel_service.zip            (zips the kestrel_service/ folder)
SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.
"""

import zipfile
from pathlib import Path

import docx

HERE = Path(__file__).parent


def make_incident_docx() -> None:
    d = docx.Document()
    d.add_paragraph('SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.')
    d.add_heading("Incident INC-007: missing readings from Greenhouse B", level=1)
    d.add_paragraph("Date: 14 Oct 2026. Severity: SEV-2. Written by: Dev. Status: resolved.")
    d.add_heading("Summary", level=2)
    d.add_paragraph(
        "From 01:40 to 07:15 no readings from the 14 sensors in Greenhouse B reached kestrel-api. "
        "During the gap the temperature in Greenhouse B rose to 36.2 C at about 06:30, above the "
        "35 C limit, but no alert was sent. Some orchids showed heat damage. "
        "About 5.5 hours of data were lost."
    )
    d.add_heading("Timeline", level=2)
    timeline = d.add_table(rows=1, cols=2)
    timeline.rows[0].cells[0].text = "Time"
    timeline.rows[0].cells[1].text = "Event"
    for time, event in [
        ("01:38", "Wi-Fi access point in Greenhouse B installs a firmware update and reboots"),
        ("01:40", "ESP32 boards in Greenhouse B lose Wi-Fi and do not reconnect"),
        ("06:30", "Greenhouse B temperature reaches 36.2 C (seen later on a backup thermometer)"),
        ("07:10", "Lena notices a flat line for Greenhouse B on the dashboard"),
        ("07:15", "Omar power-cycles the boards; readings resume"),
    ]:
        row = timeline.add_row().cells
        row[0].text = time
        row[1].text = event
    d.add_heading("Root cause", level=2)
    d.add_paragraph(
        "The ESP32 firmware connects to Wi-Fi only once at boot and has no reconnect retry. "
        "Second problem: the alert worker only checks thresholds on readings that arrive, so "
        "missing data never triggers an alert."
    )
    d.add_heading("Action items", level=2)
    actions = d.add_table(rows=1, cols=3)
    for cell, title in zip(actions.rows[0].cells, ["Action", "Owner", "Due"]):
        cell.text = title
    for action, owner, due in [
        ("Add Wi-Fi reconnect with exponential backoff to the ESP32 firmware", "Omar", "21 Oct 2026"),
        ("Alert when a sensor sends no data for 15 minutes (stale-data alert)", "Dev", "20 Oct 2026"),
        ("Buffer up to 6 hours of readings on each board and upload them when back online", "Omar", "31 Oct 2026"),
        ("Update the design notes with the stale-data alert", "Maya", "17 Oct 2026"),
    ]:
        row = actions.add_row().cells
        row[0].text, row[1].text, row[2].text = action, owner, due
    d.add_heading("Lessons learned", level=2)
    d.add_paragraph("Monitor for missing data, not only for bad values. Test firmware against Wi-Fi outages.")
    d.save(HERE / "kestrel_incident_INC-007.docx")


def make_service_zip() -> None:
    source = HERE / "kestrel_service"
    with zipfile.ZipFile(HERE / "kestrel_service.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                z.write(path, path.relative_to(source).as_posix())


if __name__ == "__main__":
    make_incident_docx()
    make_service_zip()
    print("wrote kestrel_incident_INC-007.docx and kestrel_service.zip")
