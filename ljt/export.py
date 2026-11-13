"""Excel and CSV export. Same columns in both; the Excel file is formatted as a filterable table."""
import csv
import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

# (key, header, Excel width, wrap)
COLUMNS = [
    # the job
    ("job_title", "Job Title", 38, True),
    ("location", "Location", 24, False),
    ("workplace", "Workplace", 11, False),
    ("job_description", "Job Description", 80, True),
    ("job_url", "Job URL", 44, False),
    ("job_id", "Job ID", 13, False),
    # the company, side by side
    ("company_name", "Company Name", 24, False),
    ("company_industry", "Company Industry", 28, False),
    ("company_size", "Company Size", 14, False),
    ("company_url", "Company URL", 44, False),
    ("industry_source", "Industry Source", 26, False),
    # the people hiring, then when it was collected
    ("contact_profile_links", "Contact Profile Link(s)", 42, True),
    ("first_found", "Date Collected (IST)", 18, False),
    ("last_seen", "Last Seen (IST)", 18, False),
]
DATE_COLUMNS = {"first_found", "last_seen"}


def _when(v):
    """Stored ISO time (IST) -> a real Excel date-time, or None when blank/unreadable."""
    try:
        return datetime.datetime.fromisoformat(str(v)).replace(tzinfo=None) if v else None
    except ValueError:
        return None


def _csv_value(key, v):
    if key in DATE_COLUMNS:
        d = _when(v)
        return d.strftime("%Y-%m-%d %H:%M:%S") if d else ""
    return _text(v).replace("\n", "; ") if key == "contact_profile_links" else _text(v)


EXCEL_CELL_LIMIT = 32000
LINK_COLUMNS = {"job_url", "company_url", "contact_profile_links"}


def _text(v):
    """Plain text; a value starting with = + - @ is never treated as a spreadsheet formula."""
    s = str(v or "")
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel opens UTF-8 correctly
        w = csv.writer(f)
        w.writerow([h for _, h, _, _ in COLUMNS])
        for r in rows:
            w.writerow([_csv_value(k, r.get(k)) for k, _, _, _ in COLUMNS])
    return path


def write_xlsx(rows, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Jobs"
    ws.append([h for _, h, _, _ in COLUMNS])
    head_fill, head_font = PatternFill("solid", fgColor="1F5FBF"), Font(bold=True, color="FFFFFF")
    for c in ws[1]:
        c.fill, c.font = head_fill, head_font
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30

    link_font = Font(color="1F5FBF", underline="single")
    for i, r in enumerate(rows, start=2):
        for j, (key, _, _, wrap) in enumerate(COLUMNS, start=1):
            if key in DATE_COLUMNS:                        # real dates, so they sort and filter correctly
                cell = ws.cell(row=i, column=j, value=_when(r.get(key)))
                cell.number_format = "yyyy-mm-dd hh:mm"
                cell.alignment = Alignment(vertical="top")
                continue
            value = _text(r.get(key))[:EXCEL_CELL_LIMIT]
            cell = ws.cell(row=i, column=j, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=wrap)
            if key in LINK_COLUMNS and value.startswith("http"):
                cell.hyperlink = value.split("\n")[0]       # first link clickable; all links stay visible
                cell.font = link_font
        ws.row_dimensions[i].height = 75                    # a readable preview; the full text is in the cell

    for j, (_, _, width, _) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.freeze_panes = "B2"                                  # header row and job title stay visible
    if rows:
        table = Table(displayName="Jobs", ref=f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(table)                                 # filters + banded rows
    else:
        ws.auto_filter.ref = ws.dimensions
    wb.save(path)
    return path
