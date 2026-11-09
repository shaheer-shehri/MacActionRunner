"""Language/country detection + Place-ID entry.

Covers the two regressions reported from production:

1. A sign ordered in another language printed the MARKETPLACE language instead
   (a French customer ordering an English sign got a French sign), because the
   name lookup only knew each language in its own tongue and fell back to the
   form's language for everything else. Exercised here for all 5x5 form/sign
   combinations.

2. The manual fallback only accepted a complete review link, so a Place ID
   looked up by hand -- the whole point of the fallback when the Places API
   finds no match -- was discarded.

Run from the app/ directory:  python -m unittest discover tests
"""
from __future__ import annotations

import unittest

from qrnfc import csv_parser, variants
from qrnfc.labels import DEFAULT_LABELS
from qrnfc.models import Order
from qrnfc.pipeline import resolve_link
from qrnfc.review_link import looks_like_place_id

LANGS = ["DE", "EN", "ES", "FR", "IT"]

# How each form language writes each sign-language option. Spelled out on
# purpose, independently of labels.LANGUAGE_NAMES, so that reordering or
# breaking that table fails this test instead of silently agreeing with it.
NAMES = {
    "DE": {"DE": "Deutsch",  "EN": "Englisch", "ES": "Spanisch", "FR": "Französisch", "IT": "Italienisch"},
    "EN": {"DE": "German",   "EN": "English",  "ES": "Spanish",  "FR": "French",      "IT": "Italian"},
    "ES": {"DE": "Alemán",   "EN": "Inglés",   "ES": "Español",  "FR": "Francés",     "IT": "Italiano"},
    "FR": {"DE": "Allemand", "EN": "Anglais",  "ES": "Espagnol", "FR": "Français",    "IT": "Italien"},
    "IT": {"DE": "Tedesco",  "EN": "Inglese",  "ES": "Spagnolo", "FR": "Francese",    "IT": "Italiano"},
}


def note_for(form: str, sign_value: str) -> str:
    """A note as the given form's checkout page would send it."""
    lab = DEFAULT_LABELS[form]
    return "\n".join([
        lab["language"][0] + " " + sign_value,
        lab["company"][0] + " Test Betrieb",
        lab["address"][0] + " Hauptstraße 1, 10117 Berlin",
        lab["material"][0] + " MDF Sockel Eiche Dekor",
    ])


def parse(note: str) -> Order:
    order = Order(row_index=0, order_number="1", sku="NFC_D02_BLK-A5", raw_note=note)
    csv_parser._extract_fields(order, DEFAULT_LABELS)
    return order


class LanguageAndCountryMatrix(unittest.TestCase):
    def test_every_form_and_sign_combination(self):
        """All 25 combinations: the template follows the SIGN language, while
        the form language is reported separately as the order's origin."""
        for form in LANGS:
            for sign in LANGS:
                with self.subTest(form=form, sign=sign):
                    o = parse(note_for(form, NAMES[form][sign]))
                    self.assertEqual(o.language, sign,
                                     f"{form} form ordering a {sign} sign")
                    self.assertEqual(o.form_language, form)

    def test_cross_language_order_picks_the_other_template(self):
        """The reported bug, end to end: a French customer ordering an English
        sign must resolve the EN template, not the FR one."""
        o = parse(note_for("FR", NAMES["FR"]["EN"]))
        self.assertEqual((o.form_language, o.language), ("FR", "EN"))
        v = variants.decode_variant(o)
        self.assertEqual(v.language, "EN")
        self.assertEqual(v.template_key, "EN_D02_BLK_A5")

    def test_real_order_from_the_sample_data(self):
        """German form, "Englisch" selected -- the one cross-language order
        that actually appears in the sample CSVs."""
        o = parse(note_for("DE", "Englisch"))
        self.assertEqual((o.form_language, o.language), ("DE", "EN"))

    def test_same_language_orders_are_unaffected(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                o = parse(note_for(lang, NAMES[lang][lang]))
                self.assertEqual(o.language, lang)
                self.assertEqual(o.form_language, lang)

    def test_accents_and_case_are_ignored(self):
        for value in ("ANGLAIS", "anglais", "Anglais "):
            with self.subTest(value=value):
                self.assertEqual(parse(note_for("FR", value)).language, "EN")
        self.assertEqual(parse(note_for("ES", "ingles")).language, "EN")
        self.assertEqual(parse(note_for("ES", "Inglés")).language, "EN")

    def test_decorated_value_still_resolves(self):
        self.assertEqual(parse(note_for("DE", "Deutsch / German")).language, "DE")
        self.assertEqual(parse(note_for("IT", "Italiano (IT)")).language, "IT")

    def test_unknown_selection_falls_back_but_says_so(self):
        """An unrecognised value may still fall back to the form language -- a
        batch must not die -- but it has to be visible, because a silent
        fallback is what printed the wrong language in the first place."""
        o = parse(note_for("FR", "Klingon"))
        self.assertEqual(o.form_language, "FR")
        self.assertEqual(o.language, "FR")
        self.assertTrue(any("unrecognised sign language" in n for n in o.notes), o.notes)

    def test_missing_language_line_is_reported(self):
        o = parse("Name des Unternehmens: Test Betrieb")
        self.assertIsNone(o.form_language)
        self.assertTrue(any("could not detect language" in n for n in o.notes), o.notes)

    def test_company_and_address_still_parse_in_every_form(self):
        """Guard the existing extraction while the language logic moves."""
        for form in LANGS:
            with self.subTest(form=form):
                o = parse(note_for(form, NAMES[form][form]))
                self.assertEqual(o.company, "Test Betrieb")
                self.assertIn("Hauptstraße 1", o.address)
                self.assertIn("Eiche", o.material_text)


PID = "ChIJN1t_tDeuEmsRUsoyG83frY4"
REVIEW = "https://search.google.com/local/writereview?placeid=" + PID


def resolved(**fields) -> Order:
    o = Order(row_index=0, order_number="1", sku="NFC_D02_BLK-A5", raw_note="")
    o.company = "Test Betrieb"
    for k, v in fields.items():
        setattr(o, k, v)
    resolve_link(o, cfg=None, places=None, manual_cb=lambda _o: "", resolver=None)
    return o


class ManualPlaceIdEntry(unittest.TestCase):
    def test_bare_place_id_in_the_link_field(self):
        """What the "New print file" dialog does with its Place ID box: before
        the fix this was dropped with "no url in text"."""
        o = resolved(provided_link=PID)
        self.assertEqual(o.final_link, REVIEW)
        self.assertEqual(o.place_id, PID)
        self.assertTrue(o.is_resolved)

    def test_bare_place_id_typed_into_the_manual_dialog(self):
        o = Order(row_index=0, order_number="1", sku="NFC_D02_BLK-A5", raw_note="")
        o.company = "Test Betrieb"
        resolve_link(o, cfg=None, places=None, manual_cb=lambda _o: PID, resolver=None)
        self.assertEqual(o.final_link, REVIEW)
        self.assertEqual(o.place_id, PID)

    def test_manual_entry_dialog_builds_the_link(self):
        from qrnfc.manual_entry import build_order
        o = build_order("ref-1", "DE", "D02", "BLK", "A5",
                        "Test Betrieb", "Hauptstraße 1", link=PID)
        self.assertEqual(o.place_id, PID)
        self.assertEqual(o.provided_link, REVIEW)

    def test_full_link_still_accepted(self):
        for url in (REVIEW, "https://g.page/r/CYUvPVzFwK1gEAE/review"):
            with self.subTest(url=url):
                self.assertTrue(resolved(provided_link=url).is_resolved)

    def test_company_name_in_the_link_field_is_not_a_place_id(self):
        """Customers type prose into the optional link box (the sample data has
        "RZ Installationen e.U."). A single long word must not be mistaken for
        an ID and turned into a dead review link."""
        for prose in ("Lastenradmanufaktur", "RZ Installationen e.U.", "Salon Pfotenglück"):
            with self.subTest(prose=prose):
                o = resolved(provided_link=prose)
                self.assertFalse(o.is_resolved)
                self.assertEqual(o.final_link, "")

    def test_strictness(self):
        self.assertTrue(looks_like_place_id(PID, strict=True))
        self.assertFalse(looks_like_place_id("Lastenradmanufaktur", strict=True))
        # operator-typed input is trusted: an unusual ID must not be rejected
        self.assertTrue(looks_like_place_id("ABCDEFGHIJKLMNOP"))
        self.assertFalse(looks_like_place_id("ABCDEFGHIJKLMNOP", strict=True))
        self.assertFalse(looks_like_place_id("https://g.page/r/abc/review"))
        self.assertFalse(looks_like_place_id("short"))


class Filenames(unittest.TestCase):
    """<prefix>_<lang>_<SKU>_<tracking>_<material>-<country>."""

    def name_for(self, form, sign_value, material, prefix="1x", track="TRACK123"):
        from qrnfc.pipeline import _out_name
        lab = DEFAULT_LABELS[form]
        lines = [lab["language"][0] + " " + sign_value,
                 lab["company"][0] + " Cafe X",
                 lab["address"][0] + " 18b Rue Branly 68000 Colmar"]
        if material:
            lines.append(lab["material"][0] + " " + material)
        o = Order(row_index=0, order_number="T", sku="NFC_D02_BLK-A5",
                  raw_note="\n".join(lines), tracking=track)
        csv_parser._extract_fields(o, DEFAULT_LABELS)
        variants.decode_variant(o)
        o.file_prefix = prefix
        return _out_name(o)

    def test_cross_language_shows_both_languages(self):
        """An English sign bought on the French marketplace: sign language in
        the name, marketplace as the country."""
        self.assertEqual(self.name_for("FR", "Anglais", "MDF - Decor chene"),
                         "1x_EN_NFC_D02_BLK-A5_TRACK123_OAK-FR.pdf")

    def test_same_language_order(self):
        self.assertEqual(self.name_for("DE", "Deutsch", "MDF Sockel Eiche Dekor"),
                         "1x_DE_NFC_D02_BLK-A5_TRACK123_OAK-DE.pdf")

    def test_walnut(self):
        self.assertEqual(self.name_for("IT", "Spagnolo", "MDF base effetto noce"),
                         "1x_ES_NFC_D02_BLK-A5_TRACK123_WNT-IT.pdf")

    def test_plain_mdf_leaves_country_as_the_last_part(self):
        """With no material code the trailing field is just the country -- never
        a dangling separator."""
        self.assertEqual(self.name_for("DE", "Deutsch", None),
                         "1x_DE_NFC_D02_BLK-A5_TRACK123_DE.pdf")

    def test_multi_sign_prefix_is_preserved(self):
        self.assertEqual(self.name_for("DE", "Deutsch", "Eiche", prefix="A2"),
                         "A2_DE_NFC_D02_BLK-A5_TRACK123_OAK-DE.pdf")

    def test_manual_order_follows_the_same_scheme(self):
        from qrnfc.manual_entry import build_order
        from qrnfc.pipeline import _out_name
        o = build_order("ebay-9912", "EN", "D02", "BLK", "A5", "Cafe X",
                        "Hauptstraße 1", material_text="Eiche", country="FR")
        variants.decode_variant(o)
        self.assertEqual(_out_name(o), "ebay-9912_EN_NFC_D02_BLK-A5_OAK-FR.pdf")


if __name__ == "__main__":
    unittest.main(verbosity=2)
