from fractions import Fraction
from pathlib import Path

from app.mxl2abc import convert, fmt_len, split_len

FIX = Path(__file__).parent / "fixtures"


def test_header_and_voices():
    abc = convert(str(FIX / "piano.mxl"))
    assert "T:Fixture Piece" in abc
    assert "C:Test Composer" in abc
    assert "M:4/4" in abc and "K:F" in abc
    assert "%%score {V1 | V2}" in abc
    assert "V:V2 clef=bass" in abc


def test_music_content():
    lines = convert(str(FIX / "piano.musicxml")).splitlines()
    rh = lines[lines.index("V:V1", 8) + 1]
    lh = lines[lines.index("V:V2", 8) + 1]
    assert rh == "|: [ce]2 (3=BBA G4- | G2 z2 ^F4 :|"
    assert lh == "|: F,,8 | z8 :|"


def test_compressed_and_plain_give_same_result():
    assert convert(str(FIX / "piano.mxl")) == convert(str(FIX / "piano.musicxml"))


def test_bytes_input():
    assert convert((FIX / "piano.mxl").read_bytes()).startswith("X:1")


def test_lengths():
    assert fmt_len(Fraction(1)) == ""
    assert fmt_len(Fraction(1, 2)) == "/"
    assert fmt_len(Fraction(3, 2)) == "3/2"
    assert fmt_len(Fraction(1, 4)) == "/4"
    assert split_len(Fraction(5)) == [Fraction(4), Fraction(1)]
    assert split_len(Fraction(6)) == [Fraction(6)]
