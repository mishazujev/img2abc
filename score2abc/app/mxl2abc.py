"""Convert MusicXML (.mxl / .musicxml / .xml) to ABC notation.

Written for the output of Audiveris on piano scores, but works for any
partwise MusicXML: every (part, voice) pair becomes one ABC voice, voices are
grouped onto the staves they mostly live on, and a ``%%score`` line joins the
staves of a part with a brace.

Usage:  python -m app.mxl2abc score.mxl > score.abc
"""
from __future__ import annotations

import io
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from math import gcd

# L: unit note length used for every voice
UNIT = Fraction(1, 8)

MAJOR_KEYS = {-7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb", -1: "F", 0: "C",
              1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#"}
MINOR_KEYS = {-7: "Abm", -6: "Ebm", -5: "Bbm", -4: "Fm", -3: "Cm", -2: "Gm", -1: "Dm", 0: "Am",
              1: "Em", 2: "Bm", 3: "F#m", 4: "C#m", 5: "G#m", 6: "D#m", 7: "A#m"}
SHARP_ORDER = "FCGDAEB"

TYPE_LEN = {"maxima": Fraction(8), "long": Fraction(4), "breve": Fraction(2), "whole": Fraction(1),
            "half": Fraction(1, 2), "quarter": Fraction(1, 4), "eighth": Fraction(1, 8),
            "16th": Fraction(1, 16), "32nd": Fraction(1, 32), "64th": Fraction(1, 64),
            "128th": Fraction(1, 128)}

ARTICULATIONS = {"staccato": ".", "accent": "!>!", "tenuto": "!tenuto!", "staccatissimo": "!wedge!",
                 "strong-accent": "!marcato!"}
ORNAMENTS = {"trill-mark": "!trill!", "turn": "!turn!", "mordent": "!lowermordent!",
             "inverted-mordent": "!uppermordent!"}
DYNAMICS = {"pppp": "!pppp!", "ppp": "!ppp!", "pp": "!pp!", "p": "!p!", "mp": "!mp!", "mf": "!mf!",
            "f": "!f!", "ff": "!ff!", "fff": "!fff!", "ffff": "!ffff!", "sf": "!sfz!", "sfz": "!sfz!",
            "rfz": "!sfz!", "sffz": "!sfz!", "fz": "!sfz!", "fp": '"_fp"', "sfp": '"_sfp"'}


# --------------------------------------------------------------------------- model

@dataclass
class Event:
    onset: Fraction                      # whole-note units from measure start
    dur: Fraction                        # sounding duration, whole-note units
    pitches: list = field(default_factory=list)   # [(step, alter, octave, tie_start)]
    rest: bool = False
    measure_rest: bool = False
    grace: list = field(default_factory=list)     # grace notes preceding this event
    decorations: list = field(default_factory=list)
    slur_start: int = 0
    slur_stop: int = 0
    tuplet: tuple | None = None          # (actual, normal) when time-modified
    tuplet_start: bool = False
    tuplet_stop: bool = False
    tuplet_base: Fraction | None = None  # <normal-type> value
    beam_continue: bool = False          # beamed to the next note
    prefix: list = field(default_factory=list)    # inline fields such as [K:...]


@dataclass
class Measure:
    number: str
    length: Fraction = Fraction(0)
    voices: dict = field(default_factory=lambda: defaultdict(list))   # vkey -> [Event]
    left_repeat: bool = False
    right_repeat: bool = False
    ending: str | None = None
    final_bar: str | None = None          # "|]" or "||"
    new_system: bool = False
    time: tuple | None = None             # change of time signature at this measure
    key: str | None = None                # change of key at this measure
    clefs: dict = field(default_factory=dict)   # staff -> clef string
    directions: list = field(default_factory=list)  # (staff, onset, text)


# --------------------------------------------------------------------------- reading

def read_musicxml(path_or_bytes) -> ET.Element:
    data = path_or_bytes
    if isinstance(path_or_bytes, (str, bytes)) and not (isinstance(path_or_bytes, bytes)
                                                        and path_or_bytes.lstrip()[:1] == b"<"):
        if isinstance(path_or_bytes, str):
            with open(path_or_bytes, "rb") as fh:
                data = fh.read()
    if data[:2] == b"PK":                 # compressed .mxl
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            root_name = None
            try:
                container = ET.fromstring(zf.read("META-INF/container.xml"))
                rf = container.find(".//{*}rootfile")
                if rf is not None:
                    root_name = rf.get("full-path")
            except KeyError:
                pass
            if not root_name:
                root_name = next(n for n in zf.namelist()
                                 if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
            data = zf.read(root_name)
    root = ET.fromstring(data)
    if root.tag == "score-timewise":
        raise ValueError("timewise MusicXML is not supported; please export partwise")
    return root


def _text(el, path, default=None):
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else default


# --------------------------------------------------------------------------- formatting

def fmt_len(units: Fraction) -> str:
    """ABC length suffix for a duration expressed in L: units."""
    if units == 1:
        return ""
    if units.denominator == 1:
        return str(units.numerator)
    if units.numerator == 1:
        return "/" if units.denominator == 2 else f"/{units.denominator}"
    return f"{units.numerator}/{units.denominator}"


def representable(units: Fraction) -> bool:
    """True if a note of this length can be drawn as one (possibly dotted) note."""
    for k in range(-7, 5):
        base = Fraction(2) ** k
        if units in (base, base * Fraction(3, 2), base * Fraction(7, 4)):
            return True
    return False


def split_len(units: Fraction) -> list:
    """Split a length into drawable pieces, largest first."""
    if units <= 0:
        return []
    if representable(units):
        return [units]
    pieces = []
    rest = units
    while rest > 0 and len(pieces) < 16:
        best = None
        for k in range(4, -5, -1):
            base = Fraction(2) ** k
            for c in (base * Fraction(3, 2), base):
                if c <= rest and (best is None or c > best):
                    best = c
        if best is None or best < Fraction(1, 8):   # OMR rounding residue: drop it
            break
        pieces.append(best)
        rest -= best
    return pieces


def abc_pitch(step: str, octave: int) -> str:
    if octave >= 5:
        return step.lower() + "'" * (octave - 5)
    return step.upper() + "," * (4 - octave)


def key_alterations(fifths: int) -> dict:
    alt = {}
    if fifths > 0:
        for s in SHARP_ORDER[:fifths]:
            alt[s] = 1
    elif fifths < 0:
        for s in SHARP_ORDER[::-1][: -fifths]:
            alt[s] = -1
    return alt


def acc_symbol(alter: int) -> str:
    return {-2: "__", -1: "_", 0: "=", 1: "^", 2: "^^"}.get(alter, "")


# --------------------------------------------------------------------------- converter

class Converter:
    def __init__(self, root: ET.Element):
        self.root = root
        self.measures: list[Measure] = []
        self.voice_staff: dict = {}        # vkey -> staff key (part_id, staff_no)
        self.staff_clef: dict = {}         # staff key -> initial clef
        self.part_names: dict = {}
        self.initial_time = (4, 4)
        self.initial_key = (0, "major")
        self.tempo = None

    # ---------------------------------------------------------------- parse
    def parse(self):
        for sp in self.root.iter("score-part"):
            self.part_names[sp.get("id")] = _text(sp, "part-name", "")
        staff_counts: dict = defaultdict(Counter)

        for p_index, part in enumerate(self.root.findall("part")):
            pid = part.get("id") or f"P{p_index + 1}"
            divisions = 1
            time_sig = None
            m_index = 0
            for meas in part.findall("measure"):
                if m_index >= len(self.measures):
                    self.measures.append(Measure(meas.get("number", str(m_index + 1))))
                M = self.measures[m_index]
                m_index += 1
                cursor = Fraction(0)
                max_pos = Fraction(0)
                last_onset = Fraction(0)
                pending_grace: dict = defaultdict(list)
                pending_dirs: list = []
                for el in meas:
                    tag = el.tag
                    if tag == "attributes":
                        d = _text(el, "divisions")
                        if d:
                            divisions = int(float(d))
                        t = el.find("time")
                        if t is not None and _text(t, "beats"):
                            try:
                                beats = int(_text(t, "beats").split("+")[0])
                                bt = int(_text(t, "beat-type"))
                                time_sig = (beats, bt)
                                if not self.measures[0].time and m_index == 1:
                                    self.initial_time = time_sig
                                    M.time = time_sig
                                elif m_index > 1:
                                    M.time = time_sig
                            except (TypeError, ValueError):
                                pass
                        k = el.find("key")
                        if k is not None and _text(k, "fifths") is not None:
                            fifths = int(_text(k, "fifths"))
                            mode = _text(k, "mode", "major")
                            if m_index == 1:
                                self.initial_key = (fifths, mode)
                            else:
                                M.key = self.key_name(fifths, mode)
                        for c in el.findall("clef"):
                            staff_no = c.get("number", "1")
                            clef = self.clef_name(_text(c, "sign", "G"), _text(c, "line"),
                                                  _text(c, "clef-octave-change"))
                            skey = (pid, staff_no)
                            if m_index == 1 and cursor == 0 and skey not in self.staff_clef:
                                self.staff_clef[skey] = clef
                            else:
                                M.clefs[skey] = clef
                    elif tag == "backup":
                        cursor -= Fraction(int(float(_text(el, "duration", "0"))), 4 * divisions)
                        cursor = max(cursor, Fraction(0))
                    elif tag == "forward":
                        cursor += Fraction(int(float(_text(el, "duration", "0"))), 4 * divisions)
                        max_pos = max(max_pos, cursor)
                    elif tag == "direction":
                        snd = el.find("sound")
                        if snd is not None and snd.get("tempo") and self.tempo is None:
                            try:
                                self.tempo = round(float(snd.get("tempo")))
                            except ValueError:
                                pass
                        dyn = el.find("direction-type/dynamics")
                        if dyn is not None and len(dyn):
                            name = dyn[0].tag
                            if name in DYNAMICS:
                                pending_dirs.append((_text(el, "staff", "1"), cursor, DYNAMICS[name]))
                        words = _text(el, "direction-type/words")
                        if words and len(words) < 40 and '"' not in words:
                            pending_dirs.append((_text(el, "staff", "1"), cursor, f'"^{words}"'))
                    elif tag == "print":
                        if el.get("new-system") == "yes" or el.get("new-page") == "yes":
                            M.new_system = True
                    elif tag == "barline":
                        self.read_barline(el, M)
                    elif tag == "note":
                        voice = _text(el, "voice", "1")
                        staff = _text(el, "staff", "1")
                        vkey = (pid, staff, voice)
                        staff_counts[vkey][staff] += 1
                        is_chord = el.find("chord") is not None
                        is_grace = el.find("grace") is not None
                        dur_div = _text(el, "duration")
                        pitch = self.read_pitch(el)

                        if is_grace:
                            g_len = TYPE_LEN.get(_text(el, "type", "eighth"), Fraction(1, 8))
                            if is_chord and pending_grace[vkey]:
                                continue   # keep grace chords simple: first note only
                            if pitch:
                                pending_grace[vkey].append((pitch, g_len))
                            continue

                        dur = Fraction(int(float(dur_div)), 4 * divisions) if dur_div else Fraction(0)
                        dur = self.notated_duration(el, dur)
                        cursor = snap(cursor)
                        if is_chord:
                            evs = M.voices[vkey]
                            if evs and not evs[-1].rest and evs[-1].onset == last_onset:
                                if pitch:
                                    evs[-1].pitches.append(pitch)
                                continue
                            # malformed chord flag: treat as a normal note at last onset
                            cursor = last_onset
                        ev = Event(onset=cursor, dur=dur)
                        rest_el = el.find("rest")
                        if rest_el is not None:
                            ev.rest = True
                            ev.measure_rest = rest_el.get("measure") == "yes"
                            if not dur:
                                ev.measure_rest = True
                        elif pitch:
                            ev.pitches.append(pitch)
                        tm = el.find("time-modification")
                        if tm is not None:
                            try:
                                ev.tuplet = (int(_text(tm, "actual-notes")), int(_text(tm, "normal-notes")))
                                ev.tuplet_base = TYPE_LEN.get(_text(tm, "normal-type") or _text(el, "type"))
                            except (TypeError, ValueError):
                                ev.tuplet = None
                        self.read_notations(el, ev)
                        for b in el.findall("beam"):
                            if b.get("number", "1") == "1" and b.text in ("begin", "continue"):
                                ev.beam_continue = True
                        ev.grace = pending_grace.pop(vkey, [])
                        for d in [d for d in pending_dirs if d[0] == staff]:
                            ev.decorations.insert(0, d[2])
                            pending_dirs.remove(d)
                        M.voices[vkey].append(ev)
                        last_onset = cursor
                        cursor += dur
                        max_pos = max(max_pos, cursor)
                nominal = Fraction(time_sig[0], time_sig[1]) if time_sig else Fraction(1)
                content = snap(max_pos) if max_pos else nominal
                if abs(content - nominal) <= Fraction(1, 32):
                    content = nominal
                M.length = max(M.length, content)
                M._nominal = nominal  # type: ignore[attr-defined]

        for vkey, counts in staff_counts.items():
            self.voice_staff[vkey] = (vkey[0], vkey[1])

    @staticmethod
    def notated_duration(el, dur: Fraction) -> Fraction:
        """Prefer the duration implied by <type>/<dot>/<time-modification>.

        Exporters (and OMR engines especially) round tuplet durations to integer
        divisions, e.g. 42+43+43 for a triplet; the notated value is exact.
        """
        typ = _text(el, "type")
        if typ not in TYPE_LEN or el.find("rest[@measure='yes']") is not None:
            return dur
        value = TYPE_LEN[typ]
        dots = len(el.findall("dot"))
        value = value * (2 - Fraction(1, 2 ** dots))
        tm = el.find("time-modification")
        if tm is not None:
            try:
                value = value * Fraction(int(_text(tm, "normal-notes")), int(_text(tm, "actual-notes")))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if not dur or abs(value - dur) <= Fraction(1, 32):
            return value
        return dur

    def read_pitch(self, el):
        p = el.find("pitch")
        if p is None:
            return None
        step = _text(p, "step", "C")
        alter_txt = _text(p, "alter", "0")
        try:
            alter = int(round(float(alter_txt)))
        except ValueError:
            alter = 0
        octave = int(_text(p, "octave", "4"))
        tie_start = any(t.get("type") == "start" for t in el.findall("tie"))
        return (step, alter, octave, tie_start)

    def read_notations(self, el, ev: Event):
        for n in el.findall("notations"):
            for s in n.findall("slur"):
                if s.get("type") == "start":
                    ev.slur_start += 1
                elif s.get("type") == "stop":
                    ev.slur_stop += 1
            for t in n.findall("tuplet"):
                if t.get("type") == "start":
                    ev.tuplet_start = True
                elif t.get("type") == "stop":
                    ev.tuplet_stop = True
            if n.find("fermata") is not None:
                ev.decorations.append("!fermata!")
            for a in n.findall("articulations/*"):
                if a.tag in ARTICULATIONS:
                    ev.decorations.append(ARTICULATIONS[a.tag])
            for o in n.findall("ornaments/*"):
                if o.tag in ORNAMENTS:
                    ev.decorations.append(ORNAMENTS[o.tag])
            if n.find("arpeggiate") is not None:
                ev.decorations.append("!arpeggio!")

    def read_barline(self, el, M: Measure):
        loc = el.get("location", "right")
        rep = el.find("repeat")
        style = _text(el, "bar-style")
        end = el.find("ending")
        if rep is not None:
            if rep.get("direction") == "forward":
                M.left_repeat = True
            else:
                M.right_repeat = True
        if end is not None and end.get("type") == "start":
            M.ending = (end.get("number") or "1").replace(" ", "")
        if loc == "right" and style in ("light-heavy", "heavy"):
            M.final_bar = "|]"
        elif loc == "right" and style == "light-light":
            M.final_bar = "||"

    @staticmethod
    def key_name(fifths: int, mode: str) -> str:
        fifths = max(-7, min(7, fifths))
        return MINOR_KEYS[fifths] if mode == "minor" else MAJOR_KEYS[fifths]

    @staticmethod
    def clef_name(sign: str, line: str | None, octave: str | None) -> str:
        if sign == "F":
            name = "bass"
        elif sign == "C":
            name = {"1": "soprano", "2": "mezzosoprano", "3": "alto", "4": "tenor"}.get(line or "3", "alto")
        elif sign == "percussion":
            name = "perc"
        else:
            name = "treble"
        if octave == "-1" and name == "treble":
            name += "-8"
        return name

    # ---------------------------------------------------------------- header
    def header(self) -> list[str]:
        title = (_text(self.root, "work/work-title") or _text(self.root, "movement-title") or "")
        composer = None
        for c in self.root.findall("identification/creator"):
            if c.get("type") == "composer" and c.text:
                composer = c.text.strip()
        if not title:
            for cw in self.root.findall("credit/credit-words"):
                if cw.text and cw.text.strip():
                    title = cw.text.strip()
                    break
        title = " ".join((title or "Untitled").split())
        composer = " ".join(composer.split()) if composer else None
        lines = ["X:1", f"T:{title}"]
        if composer:
            lines.append(f"C:{composer}")
        b, t = self.initial_time
        lines.append(f"M:{b}/{t}")
        lines.append(f"L:{UNIT.numerator}/{UNIT.denominator}")
        if self.tempo:
            lines.append(f"Q:1/4={self.tempo}")
        return lines

    # ---------------------------------------------------------------- output
    def convert(self) -> str:
        self.parse()
        if not self.measures:
            raise ValueError("the score contains no measures")

        # order voices: by part order, then staff, then voice number
        part_order = {p.get("id"): i for i, p in enumerate(self.root.findall("part"))}
        vkeys = sorted(self.voice_staff, key=lambda v: (part_order.get(v[0], 99),
                                                       int(self.voice_staff[v][1]) if self.voice_staff[v][1].isdigit() else 0,
                                                       int(v[2]) if v[2].isdigit() else 0))
        if not vkeys:
            raise ValueError("the score contains no notes")
        vid = {v: f"V{i + 1}" for i, v in enumerate(vkeys)}

        out = self.header()
        out.append(self.score_directive(vkeys, vid))
        for v in vkeys:
            skey = self.voice_staff[v]
            clef = self.staff_clef.get(skey, "treble")
            name = self.part_names.get(v[0], "")
            nm = f' nm="{name}"' if name and v == next(x for x in vkeys if x[0] == v[0]) and len(part_order) > 1 else ""
            out.append(f"V:{vid[v]} clef={clef}{nm}")
        key = self.key_name(*self.initial_key)
        out.append(f"K:{key}")

        # break measures into systems
        systems: list[list[int]] = []
        current: list[int] = []
        any_breaks = any(m.new_system for m in self.measures[1:])
        for i, m in enumerate(self.measures):
            if current and (m.new_system if any_breaks else len(current) >= 4):
                systems.append(current)
                current = []
            current.append(i)
        if current:
            systems.append(current)

        voice_state = {v: {"key": self.initial_key[0], "slurs": 0} for v in vkeys}
        key_fifths = self.initial_key[0]
        key_by_measure = []
        for m in self.measures:
            if m.key:
                key_fifths = self.fifths_of(m.key)
            key_by_measure.append(key_fifths)

        for sys_measures in systems:
            for v in vkeys:
                out.append(f"V:{vid[v]}")
                out.append(self.render_voice_line(v, sys_measures, key_by_measure, voice_state[v]))
        return "\n".join(out) + "\n"

    @staticmethod
    def fifths_of(key: str) -> int:
        for f, k in MAJOR_KEYS.items():
            if k == key:
                return f
        for f, k in MINOR_KEYS.items():
            if k == key:
                return f
        return 0

    def score_directive(self, vkeys, vid) -> str:
        groups = []
        part_ids = []
        for v in vkeys:
            if v[0] not in part_ids:
                part_ids.append(v[0])
        for pid in part_ids:
            staves = []
            for v in vkeys:
                if v[0] != pid:
                    continue
                s = self.voice_staff[v]
                if not staves or staves[-1][0] != s:
                    staves.append((s, []))
                staves[-1][1].append(vid[v])
            parts = []
            for _, ids in staves:
                parts.append(f"({' '.join(ids)})" if len(ids) > 1 else ids[0])
            groups.append("{" + " | ".join(parts) + "}" if len(parts) > 1 else parts[0])
        return "%%score " + " ".join(groups)

    def barline(self, i: int, last: bool) -> str:
        M = self.measures[i]
        nxt = self.measures[i + 1] if i + 1 < len(self.measures) else None
        right = ":|" if M.right_repeat else (M.final_bar or ("|]" if last and nxt is None else "|"))
        if nxt is not None and nxt.left_repeat:
            right = "::" if M.right_repeat else ("|:" if right == "|" else right + ":")
            if right == "||:":
                right = "||:"
        if nxt is not None and nxt.ending:
            right += f"[{nxt.ending}" if right.endswith(("|", ":")) else f" [{nxt.ending}"
        return right

    def render_voice_line(self, v, measure_ids, key_by_measure, state) -> str:
        parts = []
        staff = self.voice_staff[v]
        for i in measure_ids:
            M = self.measures[i]
            chunk = []
            if i == 0 and M.left_repeat:
                chunk.append("|:")
            if i == 0 and M.ending:
                chunk.append(f"[{M.ending}")
            if M.time and i > 0:
                chunk.append(f"[M:{M.time[0]}/{M.time[1]}]")
            if M.key and i > 0:
                chunk.append(f"[K:{M.key}]")
            if staff in M.clefs:
                chunk.append(f"[K:clef={M.clefs[staff]}]")
            chunk.append(self.render_measure(M, v, key_by_measure[i]))
            last_in_line = i == measure_ids[-1]
            chunk.append(self.barline(i, last_in_line))
            parts.append(" ".join(c for c in chunk if c))
        return " ".join(parts)

    def render_measure(self, M: Measure, v, fifths: int) -> str:
        events = sorted(M.voices.get(v, []), key=lambda e: e.onset)
        length = M.length
        if not events:
            return rests("x", length / UNIT)
        acc_state = dict(key_alterations(fifths))
        toks = []
        pos = Fraction(0)
        tuplet_remaining = 0
        for idx, ev in enumerate(events):
            if ev.onset > pos:                       # gap → invisible rest
                toks.append((rests("x", (ev.onset - pos) / UNIT), False))
                pos = ev.onset
            elif ev.onset < pos:
                # overlapping events in one voice (OMR glitch): drop the overlap
                if ev.onset + ev.dur <= pos:
                    continue
            dur = ev.dur
            if ev.measure_rest:
                dur = max(length - pos, dur) if dur else length - pos
            written = dur
            tup_prefix = ""
            if ev.tuplet and ev.tuplet[0] != ev.tuplet[1]:
                actual, normal = ev.tuplet
                written = dur * Fraction(actual, normal)
                if tuplet_remaining == 0:
                    count = self.tuplet_size(events, idx)
                    count = max(count, 1)
                    tup_prefix = f"({actual}:{normal}:{count}" if count != actual else f"({actual}"
                    tuplet_remaining = count
                tuplet_remaining -= 1
            else:
                tuplet_remaining = 0

            s = ""
            if ev.grace:
                g = ev.grace
                gs = "".join(self.note_str(p, acc_state) + fmt_len(gl / UNIT) for p, gl in g)
                s += "{" + gs + "}"
            s += tup_prefix
            s += "(" * ev.slur_start
            s += "".join(ev.decorations)
            if ev.rest and written / UNIT < Fraction(1, 8):
                pos += dur
                continue
            pieces = split_len(written / UNIT) or [written / UNIT]
            if ev.rest or not ev.pitches:
                s += rests("z", written / UNIT)
            else:
                ps = sorted(ev.pitches, key=lambda p: (p[2], "CDEFGAB".index(p[0])))
                names = [self.note_str(p, acc_state) for p in ps]
                for n_i, piece in enumerate(pieces):
                    last_piece = n_i == len(pieces) - 1
                    ties = ["-" if (p[3] or not last_piece) else "" for p in ps]
                    if len(ps) == 1:
                        s += names[0] + fmt_len(piece) + ties[0]
                    else:
                        s += "[" + "".join(n + t for n, t in zip(names, ties)) + "]" + fmt_len(piece)
                    if not last_piece:
                        s += " "
                    names = [abc_pitch(p[0], p[2]) for p in ps]   # accidental already applied
            s += ")" * ev.slur_stop
            beamed = (ev.beam_continue and not ev.rest and idx + 1 < len(events)
                      and events[idx + 1].onset == pos + dur and written < Fraction(1, 4))
            toks.append((s, beamed))
            pos += dur
        if pos < length:
            toks.append((rests("x", (length - pos) / UNIT), False))
        text = ""
        for t, beamed in toks:
            text += t + ("" if beamed else " ")
        return text.strip()

    @staticmethod
    def tuplet_size(events, idx) -> int:
        """Number of notes in the tuplet group starting at events[idx]."""
        first = events[idx]
        actual, normal = first.tuplet
        run = []
        for j, e2 in enumerate(events[idx:]):
            if e2.tuplet != first.tuplet or (j and e2.tuplet_start):
                break
            run.append(e2)
            if e2.tuplet_stop:
                return len(run)
        # no explicit stop: close the group once it fills `normal` base notes
        base = first.tuplet_base or min(e.dur * Fraction(actual, normal) for e in run)
        span = base * normal
        total = Fraction(0)
        for n, e2 in enumerate(run, 1):
            total += e2.dur * Fraction(actual, normal)
            if total >= span:
                return n
        return len(run)

    @staticmethod
    def note_str(p, acc_state) -> str:
        step, alter, octave, _ = p
        key = (step, octave)
        current = acc_state.get(key, acc_state.get(step, 0))
        acc = ""
        if alter != current:
            acc = acc_symbol(alter)
            acc_state[key] = alter
        return acc + abc_pitch(step, octave)


def rests(symbol: str, units: Fraction) -> str:
    return " ".join(symbol + fmt_len(u) for u in split_len(units))


def snap(x: Fraction) -> Fraction:
    """Round a time position to a 1/192-whole grid to absorb rounding drift."""
    return Fraction(round(x * 192), 192)


def convert(source) -> str:
    """Convert a MusicXML path or bytes to an ABC string."""
    return Converter(read_musicxml(source)).convert()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    sys.stdout.write(convert(sys.argv[1]))
