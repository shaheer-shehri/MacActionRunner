"""The per-order export file (``output/export.csv``) and its data contract.

    Order number | Recipient | Business name | Link | Tracking number | Filename

The interesting cases are all about granularity: the export is per ORDER while
the print files (and links.csv) are per SIGN, so an order needing several
different signs has to collapse into one row without losing anything.

Run from the app/ directory:  python -m unittest discover tests
"""
from __future__ import annotations

import csv
import os
import tempfile
import unittest

from qrnfc import csv_parser, order_export
from qrnfc.models import LinkSource, Order


def sign(order_number, company, link="", tracking="TRACK1", filename="",
         recipient="", sign_index=0, emits_file=True, resolved_name=""):
    o = Order(row_index=0, order_number=order_number, sku="NFC_D02_BLK-A5",
              raw_note="", tracking=tracking, recipient=recipient)
    o.company = company
    o.final_link = link
    o.link_source = LinkSource.PROVIDED if link else LinkSource.UNRESOLVED
    o.output_path = os.path.join("out", filename) if filename else ""
    o.sign_index = sign_index
    o.emits_file = emits_file
    o.resolved_business_name = resolved_name
    return o


class Contract(unittest.TestCase):
    def test_column_order_matches_the_contract(self):
        self.assertEqual(order_export.COLUMNS,
                         ["Order number", "Recipient", "Business name", "Link",
                          "Tracking number", "Filename"])

    def test_one_row_per_order(self):
        rows = order_export.rows_from_orders([
            sign("A-1", "Cafe One", "link1", filename="1x_a.pdf"),
            sign("A-2", "Cafe Two", "link2", filename="1x_b.pdf"),
        ])
        self.assertEqual([r.order_number for r in rows], ["A-1", "A-2"])

    def test_multi_sign_order_collapses_to_one_row(self):
        """A real case from the 2026-11-05 CSV: one order, one tracking number,
        two different branches of the same company -> A1/A2. One row, with the
        businesses, links and filenames aligned positionally."""
        rows = order_export.rows_from_orders([
            sign("304-8919424-5506734", "Strehlow Berlin-Schöneberg", "link-berlin",
                 filename="A1_DE_NFC_D02_TRP-A5_T_OAK-DE.pdf", sign_index=1),
            sign("304-8919424-5506734", "Strehlow Haldensleben", "link-halden",
                 filename="A2_DE_NFC_D02_TRP-A5_T_OAK-DE.pdf", sign_index=2),
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r.business_name,
                         "Strehlow Berlin-Schöneberg | Strehlow Haldensleben")
        self.assertEqual(r.link, "link-berlin | link-halden")
        self.assertEqual(r.filename,
                         "A1_DE_NFC_D02_TRP-A5_T_OAK-DE.pdf | "
                         "A2_DE_NFC_D02_TRP-A5_T_OAK-DE.pdf")
        # one tracking number, listed once rather than twice
        self.assertEqual(r.tracking, "TRACK1")

    def test_signs_are_listed_in_sign_order(self):
        rows = order_export.rows_from_orders([
            sign("O", "Second", "l2", filename="A2.pdf", sign_index=2),
            sign("O", "First", "l1", filename="A1.pdf", sign_index=1),
        ])
        self.assertEqual(rows[0].business_name, "First | Second")

    def test_identical_values_collapse(self):
        """Two sizes for the same business: name and link appear once, but both
        filenames are listed."""
        rows = order_export.rows_from_orders([
            sign("O", "Same Cafe", "same-link", filename="A1.pdf", sign_index=1),
            sign("O", "Same Cafe", "same-link", filename="A2.pdf", sign_index=2),
        ])
        self.assertEqual(rows[0].business_name, "Same Cafe")
        self.assertEqual(rows[0].link, "same-link")
        self.assertEqual(rows[0].filename, "A1.pdf | A2.pdf")

    def test_merged_duplicate_rows_are_skipped(self):
        """A quantity-2 order of identical signs is one print file ("2x"), so
        the business must not be listed twice."""
        rows = order_export.rows_from_orders([
            sign("O", "Cafe", "l", filename="2x_a.pdf"),
            sign("O", "Cafe", "l", emits_file=False),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].business_name, "Cafe")
        self.assertEqual(rows[0].filename, "2x_a.pdf")

    def test_unresolved_order_keeps_its_row_with_a_blank_link(self):
        """A blank cell is easier to spot than a missing row."""
        rows = order_export.rows_from_orders([sign("O", "Cafe")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].link, "")
        self.assertEqual(rows[0].filename, "")

    def test_business_name_prefers_the_resolved_listing(self):
        """The contract says this is "the company the review link points to",
        so the Places-resolved name wins over what the customer typed."""
        rows = order_export.rows_from_orders([
            sign("O", "cafe central (typo)", "l", resolved_name="Café Central GmbH")])
        self.assertEqual(rows[0].business_name, "Café Central GmbH")

    def test_recipient_is_separate_from_the_business(self):
        """"Andreas Fercher" orders a sign for "Lastenrad Manufaktur"."""
        rows = order_export.rows_from_orders([
            sign("O", "Lastenrad Manufaktur", "l", recipient="Andreas Fercher")])
        self.assertEqual(rows[0].recipient, "Andreas Fercher")
        self.assertEqual(rows[0].business_name, "Lastenrad Manufaktur")


class WrittenFile(unittest.TestCase):
    def roundtrip(self, rows):
        with tempfile.TemporaryDirectory() as d:
            path = order_export.write_csv(os.path.join(d, "export.csv"), rows)
            with open(path, newline="", encoding="utf-8-sig") as fh:
                return list(csv.reader(fh, delimiter=";"))

    def test_header_and_values(self):
        out = self.roundtrip(order_export.rows_from_orders([
            sign("O-1", "Café Pfotenglück", "https://link", tracking="T1",
                 filename="1x_a.pdf", recipient="Max Mustermann")]))
        self.assertEqual(out[0], order_export.COLUMNS)
        self.assertEqual(out[1], ["O-1", "Max Mustermann", "Café Pfotenglück",
                                  "https://link", "T1", "1x_a.pdf"])

    def test_written_with_bom_and_semicolons(self):
        """German Excel needs both: it splits on ';' and without the BOM reads
        the file as cp1252."""
        with tempfile.TemporaryDirectory() as d:
            path = order_export.write_csv(
                os.path.join(d, "export.csv"),
                order_export.rows_from_orders([sign("O", "Pfotenglück", "l")]))
            with open(path, "rb") as fh:
                raw = fh.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "missing UTF-8 BOM")
        self.assertIn(b";", raw)
        self.assertIn("Pfotenglück", raw.decode("utf-8-sig"))

    def test_append_writes_header_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "export.csv")
            rows = order_export.rows_from_orders([sign("O-1", "Cafe", "l")])
            order_export.append_rows(path, rows)
            order_export.append_rows(
                path, order_export.rows_from_orders([sign("O-2", "Bar", "l")]))
            with open(path, newline="", encoding="utf-8-sig") as fh:
                out = list(csv.reader(fh, delimiter=";"))
        self.assertEqual(out[0], order_export.COLUMNS)
        self.assertEqual([r[0] for r in out[1:]], ["O-1", "O-2"])


class RecipientColumn(unittest.TestCase):
    """The shipping export has no ship-to column yet. Reading it is wired up so
    that adding one needs no code change."""

    HEADER = ("id;order_number;item_quantity;item_sku;item_note;"
              "tracking_numbers")
    ROW = ("1;O-1;1;NFC_D02_BLK-A5;"
           '"Bitte wählen Sie eine Sprache: Deutsch'
           "\nName des Unternehmens: Divan Restaurant\";TRACK1")

    def read(self, header, row):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "parcels.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                fh.write(header + "\n" + row + "\n")
            return csv_parser.read_orders(path)

    def test_no_recipient_column_leaves_it_empty(self):
        orders = self.read(self.HEADER, self.ROW)
        self.assertEqual(orders[0].recipient, "")
        self.assertEqual(orders[0].company, "Divan Restaurant")

    def test_recipient_column_is_picked_up(self):
        for column in ("recipient", "ship_to_name", "Ship To Name",
                       "buyer_name", "empfaenger"):
            with self.subTest(column=column):
                orders = self.read(self.HEADER + ";" + column,
                                   self.ROW + ";Max Mustermann")
                self.assertEqual(orders[0].recipient, "Max Mustermann")
                # still not confused with the business being reviewed
                self.assertEqual(orders[0].company, "Divan Restaurant")


if __name__ == "__main__":
    unittest.main(verbosity=2)
