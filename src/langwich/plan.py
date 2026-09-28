"""Turn a worksheet into the lesson arc.

The order is fixed by pedagogy, not by the order tasks appear in the JSON:

1. **Before you read** — every ``warm_up`` task (pre-teach the key words,
   make a prediction).
2. **The story, scene by scene** — each scene is followed by the tasks
   anchored to it (the *last* scene a task references), sorted by stage:
   ``gist`` → ``detail`` → ``picture`` → ``form`` → ``practice``. Tasks
   without a scene are whole-story tasks and follow the last scene.
3. **Your turn** — every ``production`` task, always after the story.
4. **Take it further** — ``epilogue`` tasks (e.g. in-story homework).

The planner also makes every random choice (column order, option order,
word banks) from a seed, so the task page and the answer key agree and the
same input always produces the same worksheet.

It also finds each vocabulary item in the story (:func:`term_pattern`) to
place the side glosses; the validator uses the same patterns for its word
checks, so a word the planner can gloss is a word the validator sees.
"""

from __future__ import annotations

import functools
import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Literal

from langwich import markup
from langwich.crossword import Layout
from langwich.crossword import layout as crossword_layout
from langwich.model import (
    STAGES,
    ClassifyTask,
    ClozeTask,
    CrosswordTask,
    DialogueTask,
    Fact,
    FindInTextTask,
    GappedTextTask,
    GrammarPoint,
    LabelTask,
    MatchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    ProofreadTask,
    Scene,
    ScrambleTask,
    TableTask,
    Task,
    VocabItem,
    WordBuildingTask,
    Worksheet,
)

Phase = Literal["before", "story", "your_turn", "further"]

_STAGE_RANK = {s: i for i, s in enumerate(STAGES)}

#: Articles (and the English infinitive marker) stripped before matching a
#: vocabulary term against running text, per target language.
ARTICLES: dict[str, tuple[str, ...]] = {
    "de": ("der ", "die ", "das ", "den ", "dem ", "des ", "ein ", "eine ", "einen "),
    "fr": ("le/la ", "le ", "la ", "les ", "l'", "l’", "un ", "une ", "des ", "du "),
    "es": ("el/la ", "el ", "la ", "los ", "las ", "un ", "una ", "unos ", "unas "),
    "it": ("il ", "lo ", "la ", "l'", "l’", "i ", "gli ", "le ", "un ", "uno ", "una ", "un'"),
    "pt": ("o ", "a ", "os ", "as ", "um ", "uma ", "uns ", "umas "),
    "en": ("the ", "a ", "an ", "to "),
    "nl": ("de ", "het ", "een "),
}
# Without a known language only unambiguous articles are stripped ('de',
# 'a', 'o', 'i' are also prepositions or words in other languages).
_SAFE_ARTICLES: tuple[str, ...] = tuple(dict.fromkeys(
    a for arts in ARTICLES.values() for a in arts if a not in ("de ", "a ", "o ", "i ", "as ")
))

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

MAX_GLOSSES_PER_SCENE = 12


@dataclass
class Gloss:
    item: VocabItem
    match: str | None  # surface form in the scene text (to underline), if found


@dataclass
class Sidebar:
    grammar: GrammarPoint | None = None
    fact: Fact | None = None


@dataclass
class PlannedTask:
    number: int
    task: Task
    phase: Phase
    anchor: str | None
    #: match — display order of the right column, as indices into
    #: ``[p.right for p in pairs] + extra``.
    right_order: list[int] | None = None
    #: multiple_choice — display order of each item's options.
    option_orders: list[list[str]] | None = None
    #: order_events — events in display (shuffled) order.
    events: list[str] | None = None
    #: word bank for cloze and table (hint=word_bank), label (bank=True),
    #: dialogue (bank=True) and classify (layout=columns: the item texts).
    bank: list[str] | None = None
    #: scramble — each item's chunks in display (shuffled) order.
    tiles: list[list[str]] | None = None
    #: classify (layout=grid) — display order of the items, as indices.
    row_order: list[int] | None = None
    #: cloze (hint=choice) — the options of every gap in text order: the
    #: answer and the wrong options, shuffled.
    gap_options: list[list[str]] | None = None
    #: gapped_text — the removed sentences and the extra ones in display
    #: order (lettered A, B, C …).
    slot_options: list[str] | None = None
    #: crossword — the grid (see :func:`langwich.crossword.layout`).
    crossword: Layout | None = None
    sidebars: list[Sidebar] = field(default_factory=list)

    @property
    def right_column(self) -> list[str]:
        assert isinstance(self.task, MatchTask) and self.right_order is not None
        values = [p.right for p in self.task.pairs] + list(self.task.extra)
        return [values[i] for i in self.right_order]

    def letter_for_pair(self, pair_index: int) -> str:
        """Letter shown next to the right-hand partner of ``pairs[pair_index]``
        (A … Z, then AA, AB … like the rendered column)."""
        from langwich.answers import letter  # answers imports this module

        assert self.right_order is not None
        return letter(self.right_order.index(pair_index))

    def event_number(self, event: str) -> int:
        """Correct position (1-based) of a displayed event."""
        assert isinstance(self.task, OrderEventsTask)
        return self.task.events.index(event) + 1


@dataclass
class SceneBlock:
    number: int
    scene: Scene
    glosses: list[Gloss]
    sidebars: list[Sidebar]
    tasks: list[PlannedTask]


@dataclass
class Plan:
    worksheet: Worksheet
    seed: int
    before: list[PlannedTask]
    scenes: list[SceneBlock]
    your_turn: list[PlannedTask]
    further: list[PlannedTask]
    loose_facts: list[Fact]
    reference_grammar: list[GrammarPoint]

    @property
    def tasks(self) -> list[PlannedTask]:
        out = list(self.before)
        for block in self.scenes:
            out.extend(block.tasks)
        return out + self.your_turn + self.further


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def default_seed(ws: Worksheet) -> int:
    """The seed derived from what the worksheet says: fields left at their
    default do not count, so a new optional field in the contract does not
    reshuffle the worksheets written before it."""
    dump = ws.model_dump_json(by_alias=True, exclude_defaults=True)
    digest = hashlib.sha256(dump.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _rng(seed: int, *parts: str) -> random.Random:
    return random.Random(":".join([str(seed), *parts]))


def _shuffle_not_identity(values: list, rng: random.Random, min_len: int = 2) -> list:
    """A seeded shuffle that never returns the input order (from ``min_len``
    values on). Two match pairs or two events are always swapped: 1-A, 2-B
    would give the answer away."""
    out = list(values)
    rng.shuffle(out)
    if len(out) >= min_len and out == list(values):
        out = out[1:] + out[:1]
    return out


def strip_article(term: str, lang: str | None = None) -> str:
    """The term without a leading article (language-aware when ``lang`` is given)."""
    low = term.lower()
    articles = ARTICLES.get((lang or "").split("-")[0].lower(), _SAFE_ARTICLES)
    for art in articles:
        if low.startswith(art) and len(term) > len(art):
            return term[len(art):].strip()
    return term.strip()


def _norm(s: str, lang: str | None = None) -> str:
    return strip_article(s, lang).casefold()


# ---------------------------------------------------------------------------
# Finding a vocabulary item in running text
# ---------------------------------------------------------------------------
#
# term_pattern() compiles one regex per item with two layers:
#
# * exact — the term, its plural and its listed forms, as written;
# * loose — forms derived from them: noun and adjective endings, verb stems
#   with the inflection suffixes of the target language, German strong-verb
#   stems, separable verbs split around their clause ("gibt sie zu."),
#   reflexive verbs without their pronoun, and phrases whose words all
#   occur in one sentence.
#
# A loose match is taken only when the text holds no exact match anywhere,
# so a gloss anchors on 'sehen' rather than on an inflected look-alike.
# Stems shorter than _OPEN_TAIL_MIN letters take only the listed suffixes
# of their language (sehen must not find 'sehr', la mer not 'Merci'); longer
# stems also take a short open tail. Languages written without spaces
# (NO_SPACE_LANGS) are searched as plain substrings: \w boundaries never
# occur inside their running text.

#: Scripts written without spaces between words.
NO_SPACE_LANGS = frozenset({"zh", "ja", "th", "lo", "km", "my", "bo"})

_ROMANCE = frozenset({"fr", "es", "it", "pt"})

#: Stems with at least this many letters also take an open tail (``\w{0,n}``).
_OPEN_TAIL_MIN = 5

_ACCENT_CLASSES = {
    "e": "[eéèêë]", "a": "[aàâáã]", "i": "[iîïí]", "o": "[oôóõ]", "u": "[uùûúü]",
    "c": "[cç]",
}

#: Reflexive markers stripped before matching: the pronoun moves and changes
#: form (me/te/se, mich/dich/sich), so it is never required.
_REFLEXIVE_PREFIXES: dict[str, tuple[str, ...]] = {
    "de": ("(sich) ", "sich "),
    "fr": ("(se) ", "(s') ", "(s’) ", "se ", "s'", "s’"),
    "es": ("(se) ", "se "),
    "pt": ("(se) ", "se "),
    "it": ("(si) ", "si "),
    "": ("(sich) ", "sich ", "(se) ", "se ", "s'", "s’"),  # language unknown
}


def _words(spec: str) -> tuple[str, ...]:
    return tuple(spec.split())


#: Endings a short noun takes (Tassen, tomates, mares …). Italian swaps its
#: final vowel instead (see _noun_alts).
_NOUN_SUFFIXES: dict[str, tuple[str, ...]] = {
    "de": ("", *_words("e n en er ern s es ns ens nen")),
    "fr": ("", "s", "x"),
    "es": ("", "s", "es"),
    "pt": ("", "s", "es"),
    "en": ("", "s", "es"),
    "nl": ("", *_words("s en n 's es")),
}

_ADJ_SUFFIXES: dict[str, tuple[str, ...]] = {
    "de": ("", *_words("e en er es em ere eren erer eres erem ste sten ster stes stem")),
    "fr": ("", *_words("e s es x se ses ne nes le les te tes ve ves che ches ère ères "
                       "euse euses ienne iennes")),
    "es": ("", "s", "es", "a", "as"),
    "pt": ("", "s", "es", "a", "as"),
    "it": ("",),
    "en": ("", *_words("r st er est ly")),
    "nl": ("", *_words("e er ere st ste s")),
}
#: German adjectives ending in -e (müde → müden, müder).
_DE_ADJ_E_SUFFIXES = ("", *_words("n r s m re ren rer res rem ste sten ster stes stem"))
#: Romance adjectives after their final vowel is dropped (roj-o → roja).
_ADJ_VOWEL_SUFFIXES: dict[str, tuple[str, ...]] = {
    "fr": ("e", "es"),
    "es": _words("o a os as e es"),
    "pt": _words("o a os as e es"),
    "it": _words("o a i e"),
}

_DE_VERB_SUFFIXES = ("", *_words(
    "e st t en et est te test ten tet ete etest eten etet end ende enden ender endes "
    "endem n nd nde nden"))
_DE_PRES_SUFFIXES = ("", "st", "t")
_DE_PRET_SUFFIXES = ("", *_words("st en n t est et"))
_DE_PART_SUFFIXES = ("", *_words("e en er es em"))

_FR_ER = _words(
    "e es ent ons ez ais ait aient ions iez é ée és ées er ant a as ai âmes âtes èrent "
    "erai eras era erons erez eront erais erait erions eriez eraient eons eais eait "
    "eaient eant")
_FR_IR = ("", *_words(
    "s t is it issons issez issent issais issait issaient issions issiez i ie ies ir irai "
    "iras ira irons irez iront irais irait iraient issant isse isses ît ons ez ent ais "
    "ait aient ant"))
_FR_RE = ("", *_words(
    "s t ons ez ent ais ait aient ions iez u ue us ues re rai ras ra rons rez ront rais "
    "rait raient ant e es is it i"))
_FR_INDRE = _words(  # after 'étein-', 'pein-', 'rejoin-'
    "s t te ts tes gnons gnez gnent gnais gnait gnaient gnions gniez gnant gne gnes gnit "
    "gnirent drai dras dra drons drez dront drais drait draient")
_FR_OIR = _words("s t ons ez ent ais ait aient u ue us ues oir ra rai ras rons rez ront rait")
_ES_AR = _words(
    "o as a amos áis ais an é aste ó asteis aron aba abas ábamos abais aban ando ado ada "
    "ados adas ar aré arás ará aremos aréis arán aría arías aríamos aríais arían e es "
    "emos éis en ara aras áramos aran ase arse arme arte arnos ándose ándome ándote")
_ES_ER = _words(
    "o es e emos éis eis en í iste ió imos isteis ieron ía ías íamos íais ían iendo ido "
    "ida idos idas er eré erás erá eremos eréis erán ería erías eríamos eríais erían a as "
    "amos áis an iera ieras iéramos ieran iese erse erme erte ernos iéndose")
_ES_IR = _words(
    "o es e imos ís en í iste ió isteis ieron ía ías íamos íais ían iendo ido ida idos "
    "idas ir iré irás irá iremos iréis irán iría irías iríamos iríais irían a as amos "
    "áis an iera ieras iéramos ieran iese irse irme irte irnos iéndose")
_PT_AR = _words(
    "o as a amos ais am ei aste ou astes aram ava avas ávamos áveis avam ando ado ada "
    "ados adas ar arei arás ará aremos areis arão aria arias aríamos ariam e es emos eis "
    "em ara asse assem ássemos ares armos arem")
_PT_ER = _words(
    "o es e emos eis em i este eu estes eram ia ias íamos íeis iam endo ido ida idos "
    "idas er erei erás erá eremos ereis erão eria eriam a as amos am esse essem eres "
    "ermos erem")
_PT_IR = _words(
    "o es e imos is em i iste iu istes iram ia ias íamos iam indo ido ida idos idas ir "
    "irei irás irá iremos ireis irão iria iriam a as amos am isse issem ires irmos irem")
_IT_ARE = _words(
    "o i a iamo ate ano avo avi ava avamo avate avano ai asti ò ammo aste arono erò erai "
    "erà eremo erete eranno erei eresti erebbe eremmo ereste erebbero ando ato ata ati "
    "are arsi armi arti arci arvi andosi ino iate assi asse assero hi he hiamo hiate hino")
_IT_ERE = _words(
    "o i e iamo ete ono evo evi eva evamo evate evano ei esti é è emmo este erono etti "
    "ette ettero erò erai erà eremo erete eranno erei erebbe endo uto uta uti ute ere "
    "ersi ermi erti a ano essi esse essero")
_IT_IRE = _words(
    "o i e iamo ite ono isco isci isce iscono isca iscano ivo ivi iva ivamo ivate ivano "
    "ii isti ì immo iste irono irò irai irà iremo irete iranno irei irebbe endo ito ita "
    "iti ite ire irsi irmi irti a ano issi isse issero")
_IT_RRE = _words("co ci ce ciamo cete cono ssi sse ssero tto tta tti tte rre rrò rrà cendo")
_NL_VERB = ("", *_words("t en te ten de den d end ende"))

#: (infinitive ending, suffixes of the stem), longest ending first.
_VERB_SUFFIXES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "fr": (("oir", _FR_OIR), ("er", _FR_ER), ("ir", _FR_IR), ("re", _FR_RE)),
    "es": (("ar", _ES_AR), ("er", _ES_ER), ("ir", _ES_IR), ("ír", _ES_IR)),
    "pt": (("ar", _PT_AR), ("er", _PT_ER), ("ir", _PT_IR)),
    "it": (("are", _IT_ARE), ("ere", _IT_ERE), ("ire", _IT_IRE), ("rre", _IT_RRE)),
    "nl": (("en", _NL_VERB),),
}
#: Stressed present forms of Spanish/Italian stem-changing verbs (piensa, vuelvo, viene).
_ES_STRESSED = _words("o as a an e es en")
_ES_E_TO_I = _words("o as a an e es en amos ió ieron iendo iera ieras ieran")
_IT_STRESSED = _words("o i e a ono ano")

#: Separable German prefixes, longest first ('zurück' before 'zu').
_DE_SEPARABLE: tuple[str, ...] = tuple(sorted(set(_words(
    "ab an auf aus bei dabei daher dahin daneben dar davon dazu dazwischen durch ein "
    "empor entgegen entlang fern fest fort frei heim her herab heran herauf heraus "
    "herbei herein herüber herum herunter hervor hin hinab hinauf hinaus hinein hinter "
    "hinüber hinunter hinzu hoch kennen los mit nach nieder spazieren statt teil um "
    "unter über voran voraus vorbei vorüber vor weg weiter wieder zu zurecht zurück "
    "zusammen")), key=lambda p: (-len(p), p)))
_DE_SEPARABLE_SET = frozenset(_DE_SEPARABLE)
_DE_INSEPARABLE = ("miss", "emp", "ent", "ver", "zer", "be", "er", "ge")
_DE_NO_REGULAR = frozenset({"sein"})  # 'sei' + endings would find 'seit'

#: Common German strong and mixed verbs: infinitive, present stem with a vowel
#: change ('-' if none), preterite, participle. '/' separates variants. A '*'
#: marks a form that is also an everyday noun or adjective (der Stand, die
#: Tat, weiß): it is used only next to a separable prefix, never on its own.
#: Verbs with inseparable prefixes are derived (verstehen → verstand,
#: verstanden; gefallen → gefällt, gefiel).
_DE_STRONG_TABLE = """
backen bäck backte/buk gebacken
befehlen befiehl befahl befohlen
beginnen - begann begonnen
beißen - biss* gebissen
betrügen - betrog betrogen
biegen - bog gebogen
bieten - bot geboten
binden - band* gebunden
bitten - bat gebeten
blasen bläs blies geblasen
bleiben - blieb geblieben
braten brät briet gebraten
brechen brich brach gebrochen
brennen - brannte gebrannt
bringen - brachte gebracht
denken - dachte gedacht
dürfen darf durfte gedurft
empfehlen empfiehl empfahl empfohlen
erschrecken erschrick erschrak erschrocken
essen iss aß gegessen
fahren fähr fuhr gefahren
fallen fäll fiel gefallen
fangen fäng fing gefangen
finden - fand gefunden
fliegen - flog geflogen
fliehen - floh geflohen
fließen - floss geflossen
fressen friss fraß* gefressen
frieren - fror gefroren
geben gib gab gegeben
gehen - ging gegangen
gelingen - gelang gelungen
gelten gilt galt gegolten
genießen - genoss genossen
geschehen geschieh geschah geschehen
gewinnen - gewann gewonnen
gießen - goss gegossen
gleichen - glich geglichen
gleiten - glitt geglitten
graben gräb grub gegraben
greifen - griff* gegriffen
halten hält hielt gehalten
hängen - hing gehangen
heben - hob gehoben
heißen - hieß geheißen
helfen hilf half geholfen
kennen - kannte gekannt
klingen - klang* geklungen
kommen - kam gekommen
können kann konnte gekonnt
kriechen - kroch gekrochen
laden läd lud geladen
lassen läss ließ gelassen
laufen läuf lief gelaufen
leiden - litt gelitten
leihen - lieh geliehen
lesen lies las gelesen
liegen - lag gelegen
lügen - log gelogen
meiden - mied gemieden
messen miss maß* gemessen
mögen mag mochte gemocht
müssen muss musste gemusst
nehmen nimm nahm genommen
nennen - nannte genannt
pfeifen - pfiff gepfiffen
raten rät riet geraten
reiben - rieb gerieben
reißen - riss* gerissen
reiten - ritt* geritten
rennen - rannte gerannt
riechen - roch gerochen
rufen - rief gerufen
scheiden - schied geschieden
scheinen - schien geschienen
schieben - schob geschoben
schießen - schoss* geschossen
schlafen schläf schlief geschlafen
schlagen schläg schlug geschlagen
schleichen - schlich geschlichen
schließen - schloss* geschlossen
schneiden - schnitt* geschnitten
schreiben - schrieb geschrieben
schreien - schrie geschrien
schweigen - schwieg geschwiegen
schwimmen - schwamm* geschwommen
schwinden - schwand geschwunden
sehen sieh sah gesehen
singen - sang gesungen
sinken - sank gesunken
sitzen - saß gesessen
sprechen sprich sprach gesprochen
springen - sprang gesprungen
stechen stich stach gestochen
stehen - stand* gestanden
stehlen stiehl stahl* gestohlen
steigen - stieg gestiegen
sterben stirb starb gestorben
stinken - stank gestunken
stoßen stöß stieß gestoßen
streichen - strich* gestrichen
streiten - stritt gestritten
tragen träg trug getragen
treffen triff traf getroffen
treiben - trieb getrieben
treten tritt trat getreten
trinken - trank getrunken
tun tu tat* getan
verderben verdirb verdarb verdorben
vergessen vergiss vergaß vergessen
verlieren - verlor verloren
wachsen wächs wuchs gewachsen
waschen wäsch wusch gewaschen
weisen - wies* gewiesen
werben wirb warb geworben
werfen wirf warf geworfen
wiegen - wog gewogen
wissen weiß* wusste gewusst
wollen will wollte gewollt
ziehen - zog gezogen
zwingen - zwang gezwungen
"""

_StrongForms = tuple[tuple[str, ...], tuple[str, ...], str]


def _parse_strong(table: str) -> dict[str, _StrongForms]:
    out: dict[str, _StrongForms] = {}
    for line in table.strip().splitlines():
        inf, pres, pret, part = line.split()
        out[inf] = (tuple(pres.split("/")) if pres != "-" else (), tuple(pret.split("/")), part)
    return out


_DE_STRONG = _parse_strong(_DE_STRONG_TABLE)

#: Small endings a short listed form may still take (gab → gaben, pris → prise).
_FORM_TAILS: dict[str, tuple[str, ...]] = {
    "de": ("", "en", "n", "st", "t"),
    "fr": ("", "e", "s", "es"),
    "es": ("", "s"), "pt": ("", "s"), "it": ("", "s"),
    "en": ("", "s"),
    "nl": ("", "en", "t"),
}

_PRONOUNS_AND_AUXILIARIES = re.compile(
    r"^(?:(?:ich|du|er|sie|es|wir|ihr|je|j'|j’|tu|il|elle|on|nous|vous|ils|elles|"
    r"yo|tú|él|ella|usted|nosotros|vosotros|ellos|ellas|io|lui|lei|noi|voi|loro|"
    r"eu|ele|ela|nós|eles|elas)\s+)?"
    r"(?:(?:ist|hat|sind|haben|bin|habe|a|ai|as|ont|est|sont|suis|avons|avez|"
    r"ha|he|has|han|hemos|habéis|è|sono|ho|hanno|abbiamo|tem|têm|foi)\s+)?",
    re.IGNORECASE,
)

#: Words dropped from a listed form before its words are matched one by one
#: ('nimmt sich frei' → nimmt … frei, 'se lève' → lève).
_FORM_FILLERS = frozenset(_words(
    "ich du er sie es wir ihr je tu il elle on nous vous ils elles yo tú él ella usted "
    "nosotros vosotros ellos ellas io lui lei noi voi loro eu ele ela nós eles elas "
    "sich mich dich uns euch mir dir se me te nos os si mi ti ci vi "
    "ist hat sind haben bin habe hast habt bist seid war waren hatte a ai as ont est "
    "sont suis avons avez ha he has han hemos habéis è sono ho hanno abbiamo tem têm foi"))

#: Words too common to anchor or require when a phrase is matched word by word.
_PHRASE_STOPWORDS = frozenset(
    {a.strip().rstrip("'’").casefold() for arts in ARTICLES.values() for a in arts}
    | set(_words(
        "und oder aber mit von bei für zum zur vom beim ist sich que qui les des une del "
        "con por per sur dans pour avec the and for with una uno los las dem den der die "
        "das ein eine einen"))
)

_PUNCT = ".,;:!?¡¿\"'’«»„“”()[]…–—"
#: The window between a separable verb and its particle: one clause.
_CLAUSE_WINDOW = r"[^.!?;:,\n„“”\"«»]{1,80}?"
#: What may follow a clause-final particle.
_CLAUSE_END = (r"(?=[^\S\n]*(?:[.,!?;:…“”„\"«»‹›)\]–—]|\n|$|"
               r"(?:und|oder|aber|sondern|denn|doch)(?!\w)))")
#: The rest of a sentence (words of a phrase must share one).
_SENTENCE_REST = r"[^.!?;:\n…]*?"


def _code(lang: str | None) -> str:
    return (lang or "").split("-")[0].lower()


def _esc(text: str) -> str:
    """re.escape, with the straight and the typographic apostrophe interchangeable."""
    return "".join("['’]" if ch in "'’" else re.escape(ch) for ch in text)


def _flex(stem: str, lang: str) -> str:
    """Escaped stem; in Romance languages vowels also match their accented
    variants, because inflection moves accents (complet -> complète)."""
    if lang not in _ROMANCE:
        return _esc(stem)
    return "".join(_ACCENT_CLASSES.get(ch.lower(), _esc(ch)) for ch in stem)


def _suffix_re(suffixes: tuple[str, ...]) -> str:
    opts = sorted({s for s in suffixes if s}, key=lambda s: (-len(s), s))
    if not opts:
        return ""
    body = "(?:" + "|".join(re.escape(s) for s in opts) + ")"
    return body + "?" if "" in suffixes else body


def _alt(options: list[str]) -> str:
    return "(?:" + "|".join(dict.fromkeys(options)) + ")"


def _phrase_re(text: str) -> str:
    """A term or form as written; any run of spaces matches any whitespace."""
    return r"\s+".join(_esc(w) for w in text.split())


def _strip_reflexive(stem: str, code: str, pos: str = "verb") -> str:
    """'sich freuen' → 'freuen', "s'arrêter" → 'arrêter', 'alzarsi' → 'alzare',
    'levantarse' → 'levantar', 'levantar-se' → 'levantar'. An elided s' is a
    pronoun only before a verb ("s'il vous plaît" keeps it)."""
    low = stem.lower()
    for prefix in _REFLEXIVE_PREFIXES.get(code, ()):
        if not low.startswith(prefix) or len(stem) <= len(prefix) + 1:
            continue
        rest = stem[len(prefix):].strip()
        if prefix[-1] in "'’" and (pos != "verb" or re.match(r"ils?\b", rest, re.IGNORECASE)):
            continue
        return rest
    if code == "es" and low.endswith(("arse", "erse", "irse", "írse")):
        return stem[:-2]
    if code == "pt" and low.endswith("-se"):
        return stem[:-3]
    if code == "it" and low.endswith(("arsi", "ersi", "irsi")):
        return stem[:-2] + "e"
    if code == "it" and low.endswith(("orsi", "ursi")):
        return stem[:-3] + "rre"
    return stem


def _noun_alts(stem: str, code: str) -> list[str]:
    f = _flex(stem, code)
    alts: list[str] = []
    if code == "it":
        if len(stem) >= 3 and stem[-1:].lower() in "aeio":
            base = stem[:-1]
            h = "h?" if base[-1:].lower() in "cg" else ""
            alts.append(_flex(base, code) + h + "[aeio]")
    elif code in _NOUN_SUFFIXES:
        alts.append(f + _suffix_re(_NOUN_SUFFIXES[code]))
        low = stem.lower()
        if code == "en" and len(low) > 2 and low[-1] == "y" and low[-2] not in "aeiou":
            alts.append(re.escape(stem[:-1]) + "ies")
        elif code == "es" and low.endswith("z"):
            alts.append(_flex(stem[:-1], code) + "ces")      # luz → luces
        elif code == "fr" and low.endswith(("al", "ail")):
            alts.append(_flex(stem[: -2 if low.endswith("al") else -3], code) + "aux")
    if len(stem) >= _OPEN_TAIL_MIN:
        alts.append(f + r"\w{0,3}")
    return alts


def _adj_alts(stem: str, code: str) -> list[str]:
    low = stem.lower()
    drop = "e" if code == "fr" else "aeo"
    sfx: tuple[str, ...] | None
    if code in _ROMANCE and len(stem) >= 3 and low[-1] in drop:
        base, sfx = stem[:-1], _ADJ_VOWEL_SUFFIXES[code]
    elif code == "de" and low.endswith("e"):
        base, sfx = stem, _DE_ADJ_E_SUFFIXES
    else:
        base, sfx = stem, _ADJ_SUFFIXES.get(code)
    if len(base) < 2 or (sfx is None and len(base) < _OPEN_TAIL_MIN):
        return []
    f = _flex(base, code)
    alts = [f + _suffix_re(sfx)] if sfx else []
    if code == "en" and len(low) > 2 and low[-1] == "y" and low[-2] not in "aeiou":
        alts.append(re.escape(stem[:-1]) + "(?:ier|iest|ily)")
    if len(base) >= _OPEN_TAIL_MIN:
        alts.append(f + r"\w{0,3}")
    return alts


def _stem_change_alts(base: str, code: str, ending: str) -> list[str]:
    """Spanish e→ie/o→ue/e→i (piensa, vuelve, pide), Italian e→ie/o→uo
    (viene, muore): the stressed present forms."""
    if code not in ("es", "it"):
        return []
    m = re.search(r"([aeiouáéíóú])([^aeiouáéíóú]*)$", base.lower())
    if not m:
        return []
    vowel, i = m.group(1), m.start(1)
    head, tail = _flex(base[:i], code), re.escape(base[i + 1:])
    if code == "es":
        subs = {"e": [("ie", _ES_STRESSED)], "o": [("ue", _ES_STRESSED)],
                "u": [("ue", _ES_STRESSED)]}.get(vowel, [])
        if vowel == "e" and ending in ("ir", "ír"):
            subs = subs + [("i", _ES_E_TO_I)]
    else:
        subs = {"e": [("ie", _IT_STRESSED)], "o": [("uo", _IT_STRESSED)]}.get(vowel, [])
    return [head + new + tail + _suffix_re(sfx) for new, sfx in subs]


def _de_base(inf: str) -> str:
    """'machen' → 'mach', 'sammeln' → 'sammel', 'tun' → 'tu'."""
    if inf.endswith(("eln", "ern")):
        return inf[:-1]
    if inf.endswith("en"):
        return inf[:-2]
    if inf.endswith("n"):
        return inf[:-1]
    return inf


def _de_inseparable_prefix(inf: str) -> str | None:
    for q in _DE_INSEPARABLE:
        rest = inf[len(q):]
        if inf.startswith(q) and len(rest) >= 5 and rest.endswith("n"):
            return q
    return None


def _de_strong(inf: str) -> _StrongForms | None:
    if inf in _DE_STRONG:
        return _DE_STRONG[inf]
    q = _de_inseparable_prefix(inf)
    if q and inf[len(q):] in _DE_STRONG:
        pres, pret, part = _DE_STRONG[inf[len(q):]]
        return (tuple(q + s for s in pres), tuple(q + s for s in pret),
                q + (part[2:] if part.startswith("ge") else part))
    return None


def _de_separable_prefix(inf: str) -> str | None:
    for p in _DE_SEPARABLE:
        rest = inf[len(p):]
        if inf.startswith(p) and rest.endswith("n") and (len(rest) >= 4 or rest in _DE_STRONG):
            return p
    return None


def _de_paradigm(inf: str) -> tuple[list[str], list[str], list[str]]:
    """(finite forms, finite forms that are also nouns, participles) of a German
    verb without a separable prefix, as regex alternatives."""
    finite: list[str] = []
    ambiguous: list[str] = []
    parts: list[str] = []
    base = _de_base(inf)
    if base != inf and len(base) >= 3 and inf not in _DE_NO_REGULAR:
        b = re.escape(base)
        if len(base) >= _OPEN_TAIL_MIN:
            finite.append(b + _suffix_re(_DE_VERB_SUFFIXES))
            finite.append(b + r"\w{0,5}")
        else:  # a short bare stem is mostly a noun or adverb: mal, Reis, Wein, Land
            finite.append(b + _suffix_re(tuple(x for x in _DE_VERB_SUFFIXES if x)))
        if not (_de_inseparable_prefix(inf) or inf.endswith("ieren")):
            parts.append("ge" + b + "(?:t|et|en)" + _suffix_re(_DE_PART_SUFFIXES))
    strong = _de_strong(inf)
    if strong:
        pres, pret, part = strong
        for stem in pres:
            s = stem.rstrip("*")
            # the changed stem is an imperative (gib!, lies!) unless umlauted (fahr!)
            bare = not re.search("[äöü]", s) or s.endswith("t")
            sfx = _DE_PRES_SUFFIXES if bare else ("st", "t")
            (ambiguous if stem.endswith("*") else finite).append(re.escape(s) + _suffix_re(sfx))
        for stem in pret:
            s = stem.rstrip("*")
            target = ambiguous if stem.endswith("*") else finite
            target.append(re.escape(s) + _suffix_re(_DE_PRET_SUFFIXES))
        parts.append(re.escape(part) + _suffix_re(_DE_PART_SUFFIXES))
    return finite, ambiguous, parts


def _split(finite: str, particle: str) -> str:
    """A finite verb whose separable particle closes the same clause:
    'gibt sie zu.', 'zieht ihre Stiefel an und …' (but not 'gibt ihm etwas zu essen')."""
    return (finite + r"(?!\w)(?=" + _CLAUSE_WINDOW + r"(?<!\w)" + re.escape(particle)
            + _CLAUSE_END + ")")


def _de_verb_alts(stem: str) -> tuple[list[str], list[str]]:
    low = stem.lower()
    finite, _, parts = _de_paradigm(low)
    loose = finite + parts
    free: list[str] = []
    sep = _de_separable_prefix(low)
    if sep:
        core = low[len(sep):]
        cfin, camb, cparts = _de_paradigm(core)
        p = re.escape(sep)
        if cfin or camb:
            fin = _alt(cfin + camb)
            loose.append(p + fin)             # (dass sie es) zugibt
            loose.append(_split(fin, sep))    # gibt (sie es) zu.
            free.extend(cfin + camb)
        if cparts:
            loose.append(p + _alt(cparts))    # zugegeben, angezogen
        loose.append(p + "zu" + re.escape(core))  # zuzugeben
    return loose, free


def _en_verb_alts(stem: str) -> list[str]:
    low = stem.lower()
    if low.endswith("e"):
        return [re.escape(stem[:-1]) + "(?:e|es|ed|ing)"]
    if len(low) > 2 and low[-1] == "y" and low[-2] not in "aeiou":
        return [re.escape(stem[:-1]) + "(?:y|ies|ied|ying)"]
    alts = [re.escape(stem) + "(?:s|es|ed|ing)?"]
    if re.search(r"[^aeiou][aeiou][bdgklmnprt]$", low):
        alts.append(re.escape(stem + stem[-1]) + "(?:ed|ing)")
    return alts


def _verb_alts(stem: str, code: str) -> tuple[list[str], list[str]]:
    """(loose alternatives, finite forms of a separable verb without their
    particle) for a one-word verb."""
    if code == "de":
        return _de_verb_alts(stem)
    if code == "en":
        return _en_verb_alts(stem), []
    if code in _VERB_SUFFIXES:
        low = stem.lower()
        for ending, sfx in _VERB_SUFFIXES[code]:
            if low.endswith(ending):
                base = stem[: len(stem) - len(ending)]
                break
        else:
            return [], []
        if len(base) < 3:  # dar, ir, voir, dire: irregular, only listed forms
            return [], []
        if code == "fr" and ending == "ir" and not base.lower().endswith("t"):
            sfx = tuple(x for x in sfx if x)  # il part, il sort — but 'fin' is not finir
        f = _flex(base, code)
        alts = [f + _suffix_re(sfx)]
        if len(base) >= _OPEN_TAIL_MIN:
            alts.append(f + r"\w{0,5}")
        alts += _stem_change_alts(base, code, ending)
        if code == "fr" and low.endswith("indre"):  # éteindre → éteint, éteignent
            alts.append(_flex(stem[:-3], code) + _suffix_re(_FR_INDRE))
        if code == "nl":
            long_vowel = re.sub(r"([^aeiou])([aeou])([^aeiou])$", r"\1\2\2\3", base.lower())
            if long_vowel != base.lower():  # maken → maak, maakt
                alts.append(re.escape(long_vowel) + "(?:t|te|ten)?")
            alts.append("ge" + re.escape(base) + "(?:t|d|en)")
        return alts, []
    # language without inflection data: a conservative prefix match
    if len(stem) >= 6:
        return [re.escape(stem[:-1]) + r"\w{0,4}"], []
    return [], []


def _looks_like_infinitive(word: str, code: str) -> bool:
    low = word.lower()
    if code == "de":
        return word[:1].islower() and len(low) >= 5 and low.endswith(("en", "ern", "eln"))
    if code == "nl":
        return len(low) >= 5 and low.endswith("en")
    endings = {
        "fr": ("er", "ir", "re", "oir"),
        "es": ("ar", "er", "ir", "ír", "arse", "erse", "irse"),
        "pt": ("ar", "er", "ir"),
        "it": ("are", "ere", "ire", "arsi", "ersi", "irsi"),
    }.get(code, ())
    return bool(endings) and low.endswith(endings)


def _phrase_word(word: str, pos: str, code: str) -> str:
    """One word of a phrase with the endings it may take."""
    alts = [_esc(word)]
    if not (code == "de" and word[:1].isupper() and pos != "adjective"):
        alts += _adj_alts(word, code)
    alts += _noun_alts(word, code)
    if pos not in ("noun", "adjective") and _looks_like_infinitive(word, code):
        alts += _verb_alts(_strip_reflexive(word, code, "verb"), code)[0]
    return _alt(alts)


def _content_words(text: str, code: str) -> list[str]:
    """The words of a phrase that must all occur (articles, pronouns,
    auxiliaries and other short function words are left out)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.split():
        w = re.sub(r"^(?:[cdjlmnst]|qu)['’]", "", raw, flags=re.IGNORECASE).strip(_PUNCT)
        key = w.casefold()
        if len(w) < 3 or key in _PHRASE_STOPWORDS or key in _FORM_FILLERS or key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def _all_in_sentence(words: list[str], pos: str, code: str) -> str | None:
    """All words in one sentence, in any order; the match is the first of them."""
    if not 2 <= len(words) <= 6:
        return None
    pats = [_phrase_word(w, pos, code) for w in words]
    alts = []
    for i, pat in enumerate(pats):
        rest = "".join(rf"(?={_SENTENCE_REST}(?<!\w){o}(?!\w))"
                       for j, o in enumerate(pats) if j != i)
        alts.append(pat + r"(?!\w)" + rest)
    return "|".join(alts)


def _form_words(form: str) -> list[str]:
    out = []
    for raw in form.split():
        w = re.sub(r"^(?:[jmtsnl]|qu)['’]", "", raw, flags=re.IGNORECASE).strip(_PUNCT)
        if w and w.casefold() not in _FORM_FILLERS:
            out.append(w)
    return out


def _form_tail(word: str, code: str) -> str:
    if len(word) >= _OPEN_TAIL_MIN:
        return r"\w{0,2}"
    return _suffix_re(_FORM_TAILS.get(code, ("",)))


def _is_particle(word: str, stem: str, code: str) -> bool:
    w = word.casefold()
    if code == "de" and w in _DE_SEPARABLE_SET:
        return True
    return code in ("de", "nl") and stem.casefold().startswith(w) and len(w) < len(stem)


def _split_forms(forms: str | None, code: str) -> list[str]:
    if not forms:
        return []
    seps = r"[,;/、，；]" if code in NO_SPACE_LANGS else r"[,;/]"
    return [f.strip() for f in re.split(seps, forms) if f.strip()]


@functools.lru_cache(maxsize=8192)
def _compile(term: str, pos: str, plural: str | None, forms: str | None,
             lang: str | None) -> tuple[re.Pattern[str], re.Pattern[str] | None, bool]:
    """(search pattern, pattern of a separable verb's finite forms without
    their particle, is the term a phrase)."""
    code = _code(lang)
    stem = strip_article(term, lang)
    if code in NO_SPACE_LANGS:
        words = [stem] + ([strip_article(plural, lang)] if plural else [])
        words += _split_forms(forms, code)
        body = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True) if w)
        return re.compile(f"(?P<exact>{body})", re.IGNORECASE), None, False
    written = stem
    if pos not in ("noun", "adjective"):
        stem = _strip_reflexive(stem, code, pos)
    phrase = " " in stem
    exact = [_phrase_re(written), _phrase_re(stem)]
    loose: list[str] = []
    free: list[str] = []
    if phrase:
        group = _all_in_sentence(_content_words(stem, code), pos, code)
        if group:
            loose.append(group)
    elif pos == "noun":
        loose += _noun_alts(stem, code)
    elif pos == "adjective":
        loose += _adj_alts(stem, code)
    elif pos == "verb":
        verb_loose, verb_free = _verb_alts(stem, code)
        loose += verb_loose
        free += verb_free
    if plural:
        pl = strip_article(plural, lang)
        exact.append(_phrase_re(pl))
        if " " not in pl and len(pl) >= 3:
            loose.append(_esc(pl) + _form_tail(pl, code))
    for form in _split_forms(forms, code):
        lead = _PRONOUNS_AND_AUXILIARIES.sub("", form).strip()  # 'il a disparu' → 'disparu'
        if phrase:
            exact.append(_phrase_re(form))
            if " " in lead:  # 'est en pause' → 'en pause', but never 'a lieu' → 'lieu'
                exact.append(_phrase_re(lead))
        elif lead:
            exact.append(_phrase_re(lead))
        words = _form_words(lead or form)
        if len(words) == 1:
            w = words[0]
            if not phrase and (len(w) >= 4 or (w == lead and len(w) >= 3)):
                exact.append(_esc(w))                # 'se lève' → 'lève', not 'me río' → 'río'
                loose.append(_esc(w) + _form_tail(w, code))
        elif len(words) >= 2 and _is_particle(words[-1], stem, code):
            fin = _esc(words[0]) + _form_tail(words[0], code)
            loose.append(_split(fin, words[-1]))      # 'gibt zu' → gibt … zu.
            loose.append(_esc(words[-1]) + fin)  # (weil sie es) zugibt
            free.append(fin)
        elif len(words) >= 2:
            group = _all_in_sentence(_content_words(" ".join(words), code), pos, code)
            if group:
                loose.append(group)
    ex = "|".join(sorted(dict.fromkeys(e for e in exact if e), key=len, reverse=True))
    ex_b = rf"(?<!\w)(?:{ex})(?!\w)"
    pattern = rf"(?P<exact>{ex_b})"
    if loose:
        lo = "|".join(dict.fromkeys(loose))
        pattern += rf"|(?<!\w)(?:{lo})(?!\w)(?![\s\S]*?{ex_b})"
    free_pat = re.compile(rf"(?:{'|'.join(free)})", re.IGNORECASE) if free else None
    return re.compile(pattern, re.IGNORECASE), free_pat, phrase


def term_pattern(item: VocabItem, lang: str | None = None) -> re.Pattern[str]:
    """Regex that finds an occurrence of a vocabulary item in running text.

    The term, its plural and its listed forms match as written. Derived
    forms match too, but only where the text has no exact match: nouns and
    adjectives with the endings of the target language, verbs by stem with
    its inflection suffixes (German also by strong-verb stems and
    participles), German separable verbs split around their clause ('gibt
    sie zu.', 'zieht … an') or joined ('angezogen', 'zuzugeben'), reflexive
    verbs without their pronoun ('sich freuen' finds 'freut sich'), and
    phrases or multi-word forms whose words all occur in one sentence.
    Stems under five letters take only listed suffixes, so 'sehen' never
    finds 'sehr'. Chinese, Japanese and Thai match as plain substrings.
    ``match.group("exact")`` is set for a match of the term as written.
    """
    return _compile(item.term, item.pos, item.plural, item.forms, lang)[0]


def tested_terms(ws: Worksheet) -> set[str]:
    """Normalised words that some task asks the learner to produce or match.
    These are never glossed next to the story (the gloss would be the answer)."""
    lang = ws.target_lang
    out: set[str] = {_norm(t, lang) for t in ws.vocabulary.target}
    for task in ws.tasks:
        if isinstance(task, MatchTask):
            out.update(_norm(p.left, lang) for p in task.pairs)
            out.update(_norm(p.right, lang) for p in task.pairs)
        elif isinstance(task, LabelTask):
            scene = ws.scene(task.scene)
            if scene and scene.picture:
                out.update(_norm(lb.term, lang) for lb in scene.picture.labels)
        elif isinstance(task, WordBuildingTask):
            out.update(_norm(i.answer, lang) for i in task.items)
        elif isinstance(task, ClozeTask):
            texts = [task.text] if task.text is not None else list(task.items or [])
            for text in texts:
                out.update(_norm(g.answer, lang) for g in markup.gaps(text))
        elif isinstance(task, DialogueTask):
            for line in task.lines:
                if line.text:
                    out.update(_norm(g.answer, lang) for g in markup.gaps(line.text))
        elif isinstance(task, ClassifyTask) and task.layout == "columns":
            out.update(_norm(i.text, lang) for i in task.items)
        elif isinstance(task, (TableTask, ProofreadTask)):
            out.update(_norm(g.answer, lang) for g in _gaps_of(task))
        elif isinstance(task, FindInTextTask):
            out.update(_norm(i.answer, lang) for i in task.items)
        elif isinstance(task, CrosswordTask):
            out.update(_norm(e.answer, lang) for e in task.entries)
    return out


def _is_tested(item: VocabItem, tested: set[str], lang: str) -> bool:
    if _norm(item.term, lang) in tested:
        return True
    # an inflected answer ('geröstet', 'beliebte', 'gibt' for 'zugeben')
    # still counts as the item; a phrase counts when all its words are asked
    pattern, free, phrase = _compile(item.term, item.pos, item.plural, item.forms, lang)
    for t in tested:
        if pattern.fullmatch(t) or (free is not None and free.fullmatch(t)):
            return True
        if phrase and pattern.search(t):
            return True
    return False


def _glosses(ws: Worksheet, tested: set[str]) -> dict[str, list[Gloss]]:
    per_scene: dict[str, list[Gloss]] = {s.id: [] for s in ws.story.scenes}
    used: set[str] = set()
    lang = ws.target_lang
    candidates = [v for v in ws.vocabulary.items if not _is_tested(v, tested, lang)]
    for scene in ws.story.scenes:
        hits: list[tuple[int, int, bool, int, Gloss]] = []  # start, end, exact, order, gloss
        forced: list[Gloss] = []
        for order, item in enumerate(candidates):
            if item.term.casefold() in used:
                continue
            m = term_pattern(item, lang).search(scene.text)
            if m:
                hits.append((m.start(), m.end(), m.group("exact") is not None, order,
                             Gloss(item, m.group(0))))
            elif item.scene == scene.id:
                forced.append(Gloss(item, None))
        # Two items on the same words: the one written there exactly wins
        # (die Arbeit over arbeiten on 'Arbeit'), else the earlier item.
        kept: list[tuple[int, int, bool, int, Gloss]] = []
        for hit in sorted(hits, key=lambda h: (not h[2], h[3])):
            if all(hit[1] <= k[0] or k[1] <= hit[0] for k in kept):
                kept.append(hit)
            elif hit[4].item.scene == scene.id:
                forced.append(Gloss(hit[4].item, None))
        found = [(h[0], h[3], h[4]) for h in kept]
        found += [(len(scene.text), len(candidates), g) for g in forced]
        found.sort(key=lambda x: (x[0], x[1]))
        for _, _, g in found[:MAX_GLOSSES_PER_SCENE]:
            per_scene[scene.id].append(g)
            used.add(g.item.term.casefold())
    return per_scene


def _gaps_of(task: Task) -> list[markup.Gap]:
    if isinstance(task, ClozeTask):
        texts = [task.text] if task.text is not None else list(task.items or [])
        return [g for text in texts for g in markup.gaps(text)]
    if isinstance(task, DialogueTask):
        return [g for line in task.lines if line.text for g in markup.gaps(line.text)]
    if isinstance(task, TableTask):
        return [g for row in task.rows for cell in row if cell for g in markup.gaps(cell)]
    if isinstance(task, ProofreadTask):
        return markup.gaps(task.text)
    return []


def _dedupe(words: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for w in words:
        if w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
    return out


def _prepare(pt: PlannedTask, ws: Worksheet, seed: int) -> None:
    task = pt.task
    if isinstance(task, MatchTask):
        n = len(task.pairs) + len(task.extra)
        pt.right_order = _shuffle_not_identity(list(range(n)), _rng(seed, task.id, "right"))
    elif isinstance(task, MultipleChoiceTask):
        # Shuffle each item's options, but never let the right answer sit in
        # the same position three times in a row (a pattern learners spot).
        orders: list[list[str]] = []
        positions: list[int] = []
        for i, item in enumerate(task.items):
            rng = _rng(seed, task.id, "options", str(i))
            order = _shuffle_not_identity(item.options, rng, min_len=3)
            for _ in range(12):
                pos = order.index(item.answer)
                if len(positions) >= 2 and positions[-1] == positions[-2] == pos:
                    order = _shuffle_not_identity(item.options, rng, min_len=3)
                    continue
                break
            positions.append(order.index(item.answer))
            orders.append(order)
        pt.option_orders = orders
    elif isinstance(task, OrderEventsTask):
        pt.events = _shuffle_not_identity(task.events, _rng(seed, task.id, "events"))
    elif isinstance(task, ScrambleTask):
        _prepare_scramble(pt, task, seed)
    elif isinstance(task, ClassifyTask):
        _prepare_classify(pt, task, seed)
    elif isinstance(task, ClozeTask) and task.hint == "choice":
        _prepare_choice(pt, task, seed)
    elif isinstance(task, TableTask):
        _prepare_table(pt, task, seed)
    elif isinstance(task, GappedTextTask):
        _prepare_gapped_text(pt, task, seed)
    elif isinstance(task, CrosswordTask):
        _prepare_crossword(pt, task, seed)
    elif isinstance(task, ClozeTask) and task.hint == "word_bank":
        words = _dedupe([g.answer for g in _gaps_of(task)] + list(task.distractors))
        _rng(seed, task.id, "bank").shuffle(words)
        pt.bank = words
    elif isinstance(task, DialogueTask) and task.bank:
        words = _dedupe([g.answer for g in _gaps_of(task)] + list(task.distractors))
        _rng(seed, task.id, "bank").shuffle(words)
        pt.bank = words
    elif isinstance(task, LabelTask) and task.bank:
        scene = ws.scene(task.scene)
        if scene and scene.picture and scene.picture.labels:
            # the box shows bare words: the learner adds the article (the key has it)
            words = _dedupe([strip_article(lb.term, ws.target_lang)
                             for lb in scene.picture.labels])
            _rng(seed, task.id, "bank").shuffle(words)
            pt.bank = words


def _prepare_scramble(pt: PlannedTask, task: ScrambleTask, seed: int) -> None:
    """``pt.tiles``: each item's chunks shuffled, never in a correct order."""
    # (spine stub: the scramble implementation shuffles the tiles)


def _prepare_classify(pt: PlannedTask, task: ClassifyTask, seed: int) -> None:
    """``pt.row_order`` (grid) or ``pt.bank`` (columns: the item texts, shuffled)."""
    if task.layout == "columns":
        words = [i.text for i in task.items]
        _rng(seed, task.id, "bank").shuffle(words)
        pt.bank = words
    # (spine stub: the classify implementation adds the grid's row order)


def _prepare_choice(pt: PlannedTask, task: ClozeTask, seed: int) -> None:
    """``pt.gap_options``: the options of every choice gap, shuffled."""
    # (spine stub: the cloze choice implementation shuffles the options)


def _prepare_table(pt: PlannedTask, task: TableTask, seed: int) -> None:
    """``pt.bank`` for a table with a word box (like a word-bank cloze)."""
    if task.hint == "word_bank":
        words = _dedupe([g.answer for g in _gaps_of(task)] + list(task.distractors))
        _rng(seed, task.id, "bank").shuffle(words)
        pt.bank = words


def _prepare_gapped_text(pt: PlannedTask, task: GappedTextTask, seed: int) -> None:
    """``pt.slot_options``: the removed sentences and the extras, shuffled."""
    # (spine stub: the gapped_text implementation shuffles the sentences)


def _prepare_crossword(pt: PlannedTask, task: CrosswordTask, seed: int) -> None:
    """``pt.crossword``: the grid (seed-free, so the validator sees the same one)."""
    pt.crossword = crossword_layout([e.answer for e in task.entries])


def _phase(task: Task) -> Phase:
    if task.stage == "warm_up":
        return "before"
    if task.stage == "production":
        return "your_turn"
    if task.stage == "epilogue":
        return "further"
    return "story"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def plan(ws: Worksheet, seed: int | None = None) -> Plan:
    seed = default_seed(ws) if seed is None else seed
    scene_order = {s.id: i for i, s in enumerate(ws.story.scenes)}
    last_scene = ws.story.scenes[-1].id

    before: list[tuple[int, Task]] = []
    your_turn: list[tuple[int, Task]] = []
    further: list[tuple[int, Task]] = []
    by_scene: dict[str, list[tuple[int, Task]]] = {s.id: [] for s in ws.story.scenes}

    for idx, task in enumerate(ws.tasks):
        phase = _phase(task)
        if phase == "before":
            before.append((idx, task))
        elif phase == "your_turn":
            your_turn.append((idx, task))
        elif phase == "further":
            further.append((idx, task))
        else:
            known = [s for s in task.scene_ids if s in scene_order]
            anchor = max(known, key=scene_order.__getitem__) if known else last_scene
            by_scene[anchor].append((idx, task))

    number = 0

    def make(entries: list[tuple[int, Task]], phase: Phase, anchor: str | None) -> list[PlannedTask]:
        nonlocal number
        out = []
        for _, task in entries:
            number += 1
            pt = PlannedTask(number=number, task=task, phase=phase, anchor=anchor)
            _prepare(pt, ws, seed)
            out.append(pt)
        return out

    planned_before = make(before, "before", None)
    blocks: list[SceneBlock] = []
    tested = tested_terms(ws)
    glosses = _glosses(ws, tested)
    for i, scene in enumerate(ws.story.scenes):
        entries = sorted(by_scene[scene.id], key=lambda e: (_STAGE_RANK[e[1].stage], e[0]))
        blocks.append(SceneBlock(
            number=i + 1, scene=scene, glosses=glosses[scene.id], sidebars=[],
            tasks=make(entries, "story", scene.id),
        ))
    planned_turn = make(your_turn, "your_turn", None)
    planned_further = make(further, "further", None)

    all_tasks = planned_before + [t for b in blocks for t in b.tasks] + planned_turn + planned_further
    block_by_id = {b.scene.id: b for b in blocks}

    # Grammar: beside the first task that references it; else beside the
    # first form/practice task of its scene; else beside its scene; else
    # in the back matter.
    reference_grammar: list[GrammarPoint] = []
    for gp in ws.grammar:
        target = next((pt for pt in all_tasks if pt.task.grammar == gp.id), None)
        if target is None and gp.scene in block_by_id:
            block = block_by_id[gp.scene]
            target = next((pt for pt in block.tasks if pt.task.stage in ("form", "practice")), None)
            if target is None:
                block.sidebars.append(Sidebar(grammar=gp))
                continue
        if target is None:
            reference_grammar.append(gp)
        else:
            target.sidebars.append(Sidebar(grammar=gp))

    loose_facts: list[Fact] = []
    for fact in ws.facts:
        if fact.scene in block_by_id:
            block_by_id[fact.scene].sidebars.append(Sidebar(fact=fact))
        else:
            loose_facts.append(fact)

    return Plan(
        worksheet=ws, seed=seed, before=planned_before, scenes=blocks,
        your_turn=planned_turn, further=planned_further,
        loose_facts=loose_facts, reference_grammar=reference_grammar,
    )
