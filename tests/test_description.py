"""Περιγραφές του Google Calendar: HTML → κείμενο με μορφή για το παράθυρο υπενθύμισης."""
import pytest

import app

# Όπως τα γράφει το Google Calendar στο ICS (DESCRIPTION, μετά το ξε-escape του icalendar).
GOOGLE_LIST = ("<b>Παραλαβή κρέατος</b><br>Ελέγξτε:<ul><li>Θερμοκρασία ψυγείου&nbsp;1</li>"
               "<li>Τιμολόγιο &amp; ζύγιση<ul><li>μοσχάρι</li><li>κοτόπουλο</li></ul></li>"
               "<li><i>Υπογραφή</i> στο δελτίο</li></ul>Ευχαριστώ!")
GOOGLE_OL = ("Βήματα:<ol><li>Άνοιγμα <u>ταμείου</u></li><li>Έλεγχος <strong>ρέστων</strong></li>"
             "<li>Κλείσιμο</li></ol>")
GOOGLE_LINK = ('Οδηγίες <a href="https://www.google.com/url?q=https://example.com/odigies&amp;sa=D">εδώ</a>'
               '<br><br><br><br>Τηλ. <a href="tel:2101234567">210 1234567</a>')
GOOGLE_BLOB = ('<html-blob><span>Πελάτης Χ κατά τις 12:00</span><br><span>για έκδοση&nbsp;πληρωμής'
               '</span></html-blob>')


def text(s):
    return app.description_text(s)


def styled(s):
    return {t: (set(st), h) for t, st, h in app.description_runs(s) if st or h}


@pytest.mark.parametrize("plain", [
    "Πάρε τηλέφωνο τον πελάτη.",
    "Γραμμή 1\nΓραμμή 2\n\nΠαράγραφος - με * αστερίσκους",
    "Τιμή < 5€ και > 2€ & ΦΠΑ",
    "1. ένα\n2. δύο",
])
def test_plain_text_unchanged(plain):
    assert app.looks_like_html(plain) is False
    assert text(plain) == plain
    assert app.description_runs(plain) == [(plain, frozenset(), None)]


def test_plain_text_blank_lines_collapsed_like_before():
    assert text("  α\n\n\n\nβ  ") == "α\n\nβ"
    assert app.description_runs("") == [] and text(None) == ""


def test_google_nested_list_bold_italic_entities():
    assert text(GOOGLE_LIST) == ("Παραλαβή κρέατος\nΕλέγξτε:\n"
                                 "• Θερμοκρασία ψυγείου 1\n"
                                 "• Τιμολόγιο & ζύγιση\n"
                                 "    ◦ μοσχάρι\n"
                                 "    ◦ κοτόπουλο\n"
                                 "• Υπογραφή στο δελτίο\n"
                                 "Ευχαριστώ!")
    s = styled(GOOGLE_LIST)
    assert s["Παραλαβή κρέατος"] == ({"bold"}, None)
    assert s["Υπογραφή"] == ({"italic"}, None)
    assert "<" not in text(GOOGLE_LIST) and "&" not in text(GOOGLE_LIST).replace("& ", "")


def test_numbered_list_and_underline():
    assert text(GOOGLE_OL) == "Βήματα:\n1. Άνοιγμα ταμείου\n2. Έλεγχος ρέστων\n3. Κλείσιμο"
    s = styled(GOOGLE_OL)
    assert s["ταμείου"] == ({"underline"}, None) and s["ρέστων"] == ({"bold"}, None)


def test_two_lists_restart_numbering_and_bullets_after_text():
    t = text("<ol><li>α</li><li>β</li></ol>κείμενο<ol><li>γ</li></ol><ul><li>δ</li></ul>")
    assert t == "1. α\n2. β\nκείμενο\n1. γ\n• δ"


def test_links_show_text_and_keep_safe_href_only():
    assert text(GOOGLE_LINK) == "Οδηγίες εδώ\n\nΤηλ. 210 1234567"
    s = styled(GOOGLE_LINK)
    assert s["εδώ"][1] == "https://www.google.com/url?q=https://example.com/odigies&sa=D"
    assert "210 1234567" not in s  # tel: δεν γίνεται σύνδεσμος, μένει απλό κείμενο
    assert text('Δες <a href="https://example.com/x"></a>.') == "Δες https://example.com/x."


def test_google_html_blob_spans_and_nbsp():
    assert text(GOOGLE_BLOB) == "Πελάτης Χ κατά τις 12:00\nγια έκδοση πληρωμής"


def test_paragraphs_divs_entities_unknown_tags_and_whitespace():
    src = ('<p>Γραμμή&nbsp;&nbsp;  1 </p><p></p><p></p><div><font color="red">Κόκκινο</font></div>'
           '<script>alert(1)</script><style>p{}</style>&lt;όχι ετικέτα&gt; &#8364; &euro; &quot;ok&quot;')
    assert text(src) == 'Γραμμή 1\nΚόκκινο\n<όχι ετικέτα> € € "ok"'


def test_mixed_newlines_and_br_keep_at_most_one_blank_line():
    assert text("α<br>\nβ<br><br><br><br>γ\n\n\n<p>δ</p>") == "α\n\nβ\n\nγ\n\nδ"


def test_bold_italic_nested_and_unclosed_tags():
    s = styled("<b>Έντονο <i>και πλάγιο</i></b> <b>ανοιχτό")
    assert s["Έντονο "] == ({"bold"}, None)
    assert s["και πλάγιο"] == ({"bold", "italic"}, None)
    assert s["ανοιχτό"] == ({"bold"}, None)


def test_list_items_with_paragraphs_and_br_inside():
    src = "<ul><li><p>Ένα</p></li><li>Δύο<br>συνέχεια</li></ul>"
    assert text(src) == "• Ένα\n• Δύο\nσυνέχεια"
