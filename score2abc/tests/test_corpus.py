"""Smoke-test the converter on real scores from the music21 corpus (optional)."""
import pytest

music21 = pytest.importorskip("music21")
from music21 import corpus  # noqa: E402

from app.mxl2abc import convert  # noqa: E402

WORKS = ["joplin/maple_leaf_rag.mxl", "schubert/Lindenbaum.xml", "beach/prayer_of_a_tired_child.musicxml",
         "schumann_clara/opus17/movement3.xml", "mozart/k155/movement1.mxl", "bach/bwv66.6.mxl"]


@pytest.mark.parametrize("work", WORKS)
def test_corpus_work_converts(work):
    path = corpus.getComposer("bach")[0].parents[1] / work
    abc = convert(str(path))
    assert abc.startswith("X:1") and "K:" in abc
