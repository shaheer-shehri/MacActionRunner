"""
Generate a SANITIZED Buy Boxes template workbook (no real builder contacts).

This template is what gets bundled inside the public build. On first launch the
app copies it next to itself as 'Master_Buyer_Buy_Boxes.xlsx'; the operator then
replaces the example rows with their real builders and keeps that file locally.

Run:  python tools/make_template_workbook.py [output_path]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BUY_BOX_COLUMNS = [
    "BuyBoxID", "Builder", "Market", "County", "City/Area", "ZIP Codes",
    "Min Acres", "Max Acres", "Min Width Ft", "Min Depth Ft", "Residential Only",
    "Off Market Only", "Water Requirement", "Sewer/Septic Requirement",
    "Road Requirement", "Excluded Roads/Areas", "Price Min", "Price Max",
    "Feasibility Days", "Closing Terms", "Assignment Allowed", "Title Requirement",
    "Special Criteria", "Source Date", "Active", "Automation Notes",
]

# Two clearly-fake example rows (Active = No) that show the two matching styles:
# ZIP-based and City-based. They will NOT create matches while Active = No.
EXAMPLE_ROWS = [
    {
        "BuyBoxID": "EXAMPLE-ZIP", "Builder": "EXAMPLE Homes (replace me)",
        "Market": "Example Market", "County": "St. Lucie",
        "City/Area": "Port St. Lucie", "ZIP Codes": "34952, 34953, 34986, 34983",
        "Min Acres": "0.20", "Max Acres": "0.40", "Residential Only": "Yes",
        "Price Min": "90000", "Price Max": "150000", "Active": "No",
        "Special Criteria": "Delete this row and add your real builders.",
        "Automation Notes": "Matches on County + ZIP + Acreage.",
    },
    {
        "BuyBoxID": "EXAMPLE-CITY", "Builder": "EXAMPLE Builders LLC (replace me)",
        "Market": "Example Market", "County": "Brevard",
        "City/Area": "Palm Bay", "ZIP Codes": "",
        "Min Acres": "0.15", "Max Acres": "0.30", "Residential Only": "Yes",
        "Price Min": "25000", "Price Max": "60000", "Active": "No",
        "Special Criteria": "When ZIPs are blank, matching falls back to City/Area.",
        "Automation Notes": "Matches on County + City + Acreage.",
    },
]

CONTACTS_COLUMNS = ["Builder", "Contact", "Title", "Email", "Phone",
                    "Market/Division", "Notes"]
CONTACTS_EXAMPLE = [{
    "Builder": "EXAMPLE Homes (replace me)", "Contact": "Jane Doe",
    "Title": "Land Acquisition", "Email": "name@example.com",
    "Phone": "000-000-0000", "Market/Division": "Example Division",
    "Notes": "Replace with your real builder contacts. Kept locally only.",
}]

GUIDE_ROWS = [
    ["County / City / ZIP", "Usually yes", "Automatic hard filter"],
    ["Acreage", "Yes", "Automatic hard filter + drives star rating"],
    ["Residential vacant land", "Yes (from land-use description)", "Automatic"],
    ["Price target", "No seller ask price in assessor data",
     "Used as resale ceiling in the star score, not a hard filter"],
    ["Water / sewer / septic", "Usually not reliably",
     "Flagged in Needs_Verification for manual check"],
    ["Lot width / depth", "Usually not (needs GIS/plat)",
     "Flagged in Needs_Verification"],
    ["Road exclusions", "Partially", "Flagged in Needs_Verification"],
]

ADD_NEW_ROWS = [
    ["HOW TO ADD A BUILDER:"],
    ["1. Go to the 'Buy Boxes' sheet."],
    ["2. Add one row per buying criterion (a builder can have several rows)."],
    ["3. Fill County, City/Area or ZIP Codes, Min/Max Acres, Price Min/Max."],
    ["4. Set Active = Yes. Set Active = No to switch a buy box off without deleting."],
    ["5. Save the file and run the app again. No code changes needed."],
    [""],
    ["Add the builder's contact person on the 'Contacts' sheet (matched by Builder name)."],
]


def build(output: Path) -> None:
    buy = pd.DataFrame(EXAMPLE_ROWS)
    for col in BUY_BOX_COLUMNS:
        if col not in buy.columns:
            buy[col] = ""
    buy = buy[BUY_BOX_COLUMNS]

    contacts = pd.DataFrame(CONTACTS_EXAMPLE)[CONTACTS_COLUMNS]
    guide = pd.DataFrame(GUIDE_ROWS, columns=["FIELD", "CAN MATCH FROM COUNTY DATA NOW?", "ACTION"])
    add_new = pd.DataFrame(ADD_NEW_ROWS)

    output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        buy.to_excel(writer, sheet_name="Buy Boxes", index=False)
        contacts.to_excel(writer, sheet_name="Contacts", index=False)
        guide.to_excel(writer, sheet_name="Automation Guide", index=False)
        add_new.to_excel(writer, sheet_name="Add New Buyer", index=False, header=False)
    print(f"Wrote template: {output}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("template/Master_Buyer_Buy_Boxes.xlsx")
    build(out)
