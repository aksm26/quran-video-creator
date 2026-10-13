"""Regenerates quran_video/config/translations.py (every Quran.com translation) and language_names.py (language
names in each app language, from the Unicode CLDR). Development tool only: needs `pip install babel`.

    .venv/bin/pip install babel && .venv/bin/python tools/generate_language_data.py

Run it again if Quran.com adds translations, or to add an app language (also add it to i18n.py)."""
import collections
import pathlib
import sys

OUT = pathlib.Path(__file__).resolve().parents[1] / "quran_video" / "config"
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from babel import Locale
from quran_video.api.client import QuranClient
UI = ["en","ar","ur","fr","es","id","tr","pt","de","ru","it","nl","fa","ms","hi","bn","zh","ja"]
MAP = {'english':'en','urdu':'ur','turkish':'tr','bengali':'bn','russian':'ru','malayalam':'ml','spanish':'es','french':'fr','tajik':'tg','indonesian':'id','tamil':'ta','uzbek':'uz','bosnian':'bs','albanian':'sq','kurdish':'ku','azeri':'az','persian':'fa','japanese':'ja','italian':'it','swahili':'sw','thai':'th','kazakh':'kk','vietnamese':'vi','korean':'ko','portuguese':'pt','chinese':'zh','hausa':'ha','german':'de','bambara':'bm','divehi, dhivehi, maldivian':'dv','uighur, uyghur':'ug','tagalog':'tl','ukrainian':'uk','telugu':'te','marathi':'mr','hebrew':'he','gujarati':'gu','ganda':'lg','dutch':'nl','amharic':'am','swedish':'sv','central khmer':'km','malay':'ms','finnish':'fi','czech':'cs','tatar':'tt','romanian':'ro','polish':'pl','norwegian':'no','bulgarian':'bg','chechen':'ce','amazigh':'zgh','sindhi':'sd','yoruba':'yo','somali':'so','maranao':'mrw','nepali':'ne','oromo':'om','sinhala, sinhalese':'si','hindi':'hi','assamese':'as','pashto':'ps','kannada':'kn','dari':'fa_AF','divehi':'dv','yau,yuw':'yao','kinyarwanda':'rw'}
rows = QuranClient()._json("v4/resources/translations")["translations"]
en = Locale("en").languages
def en_name(code, api):
    return en.get(code) or en.get(code.replace("_","-")) or api.split(",")[0].strip().title()
items, seen = [], set()
for t in rows:
    if "transliteration" in (t["name"] + str(t.get("slug"))).lower():
        continue  # a transliteration is not a translation
    api = t["language_name"].strip().lower(); code = MAP[api]
    lang = en_name(code, api); key = f'{lang} ({t["name"].strip()})'
    if key in seen: key = f'{key} #{t["id"]}'
    seen.add(key); items.append((lang, key, t["id"], code, t["name"].strip()))
items.sort(key=lambda x: (x[3] != "en", x[0], x[1] != "English (Saheeh International)", x[1]))
out = ['"""Every Quran translation Quran.com offers (generated from /v4/resources/translations, October 2026).',
       '',
       'The key is a stable English label used in settings and on the command line; the app shows the language in the',
       'user\'s own language instead (see language_names.py)."""','',
       'from dataclasses import dataclass','','',
       '@dataclass(frozen=True)','class Translation:','    key: str','    id: int','    lang: str  # language code',
       '    translator: str','','','LIST: tuple[Translation, ...] = (']
for lang, key, id_, code, name in items:
    out.append(f"    Translation({key!r}, {id_}, {code!r}, {name!r}),")
out += [')','','TRANSLATIONS: dict[str, int | None] = {"None": None, **{t.key: t.id for t in LIST}}',
        'BY_KEY: dict[str, Translation] = {t.key: t for t in LIST}',
        'DEFAULT_TRANSLATION = LIST[0].key  # English, Saheeh International','',
        '','def key_for_id(translation_id: int | None) -> str:','    """The key of the translation with this Quran.com id ("None" for no translation)."""',
        '    return next((t.key for t in LIST if t.id == translation_id), "None")','']
open(str(OUT / "translations.py"),"w",encoding="utf8").write("\n".join(out))
codes = sorted({i[3] for i in items} | set(UI))
names = {}
for ui in UI:
    loc = Locale(ui); table = {}
    for c in codes:
        n = loc.languages.get(c) or loc.languages.get(c.replace("_","-")) or en.get(c) or en.get(c.replace("_","-")) or next((i[0] for i in items if i[3]==c), c)
        table[c] = n[0].upper()+n[1:]
    names[ui] = table
lines = ['"""Language names in each app language, from the Unicode CLDR (generated once; no runtime dependency).','','NAMES[app language][language code] is how that language is called in the app language, e.g. Spanish in Portuguese is "Espanhol"."""','','NAMES: dict[str, dict[str, str]] = {']
for ui in UI:
    lines.append(f"    {ui!r}: {{")
    for c, n in names[ui].items(): lines.append(f"        {c!r}: {n!r},")
    lines.append("    },")
lines += ['}','','','def language_name(code: str, ui: str) -> str:','    return NAMES.get(ui, NAMES["en"]).get(code) or NAMES["en"].get(code, code)','']
open(str(OUT / "language_names.py"),"w",encoding="utf8").write("\n".join(lines))
print(len(items),"translations;",len(codes),"language codes;",len(UI),"app languages")
print(names["pt"]["es"], names["pt"]["pt"], names["ja"]["en"], names["en"]["fa_AF"], names["ar"]["mrw"])
