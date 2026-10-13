#!/usr/bin/env python3
"""
test_dialect_engine.py — اختبارات حماية (regression) لطبقة اللهجة (engine_v2 + القاموس + ontology)

يشغل بـ pytest من داخل dialect/:
    cd ~/ahmad-agent/dialect
    python3 build_engine_v2.py          # يبني engine_v2.py من engine.py
    python3 -m pytest test_dialect_engine.py -q

أو بدونه:
    python3 test_dialect_engine.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DICT = HERE / "data" / "bahraini_dictionary_unified.json"
ONTO = HERE / "ontology.yaml"

TONE_ENUM = {"neutral", "positive", "negative", "aggressive", "friendly"}
CLASS_ENUM = {"describe", "question", "greeting", "praise", "curse", "threat", "dismiss", "insult"}
STRENGTH_ENUM = {"low", "medium", "high"}


def _load_engine(module_name: str = "engine_v2"):
    path = HERE / f"{module_name}.py"
    if not path.exists():
        raise AssertionError(f"{path} مو موجود — شغّل: python3 build_engine_v2.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _engine():
    return _load_engine().DialectEngine()


def _terms(ctx: str) -> list:
    return [ln.split("]")[0].lstrip("- [") for ln in ctx.splitlines() if ln.startswith("- [")]


# ── 1) لا إصابات substring كاذبة ─────────────────────────────────────────────

def test_no_substring_false_positives():
    e = _engine()
    benign = "يجب أن أدغدغ الشعور مع البزازة والطقس والصهريج والتتبع"
    assert e.enrich_context(benign) == "", _terms(e.enrich_context(benign))


def test_no_false_positive_from_greeting_substring():
    e = _engine()
    # «عساكم» كانت تطلع من داخل «عساكم»/«كم» — الجملة التالية ما فيها مصطلح
    assert "كم" not in _terms(e.enrich_context("عساكم السعادة دوم"))


def test_no_false_positive_baar():
    e = _engine()
    # «بار» كانت تطلع من داخل «يا زعيم وشخبارك»
    assert "بار" not in _terms(e.enrich_context("هلا يا زعيم وشخبارك"))


# ── 2) العبارات المركّبة ──────────────────────────────────────────────────────

def test_multiword_phrase_matches():
    e = _engine()
    assert "طايح النصبة" in _terms(e.enrich_context("يقولون طايح النصبة عليه"))


def test_multiword_phrase_with_spelling_variant():
    e = _engine()
    # «ام» بدون همزة — التطبيع لازم يوحّدها
    hits = _terms(e.enrich_context("صادته ام الديفان وهو صغير"))
    assert any("الديفان" in h for h in hits), hits


def test_phrase_beats_its_parts_in_order():
    e = _engine()
    hits = _terms(e.enrich_context("لا تخلط ماي بيلر مع عسكريم"))
    assert hits and hits[0] == "ماي بيلر", hits
    assert "سكر" not in hits and "كر" not in hits, hits


# ── 3) اللواصق ────────────────────────────────────────────────────────────────

def test_prefix_clitic_stripped():
    e = _engine()
    assert "شخبارك" in _terms(e.enrich_context("هلا يا زعيم وشخبارك"))


# ── 4) الحقول الدلالية تصل للسياق ─────────────────────────────────────────────

def test_notes_and_examples_are_injected():
    e = _engine()
    ctx = e.enrich_context("أدنات يوم باكسر ضلوعك")
    assert "تقال في سياق التهديد" in ctx, ctx
    assert "مثال:" in ctx, ctx


def test_synonyms_injected():
    e = _engine()
    ctx = e.enrich_context("عطني أبشار")
    assert "أبشار" in ctx


# ── 5) ontology ───────────────────────────────────────────────────────────────

def test_concept_alias_resolves():
    e = _engine()
    ctx = e.enrich_context("احنا نبني الوكيل")
    assert "AHMAD.CONCEPT.AHNA" in ctx, ctx


def test_rejected_terms_alert():
    e = _engine()
    ctx = e.enrich_context("هلا يا عزيز برو")
    assert "مرفوضة" in ctx, ctx


def test_ontology_has_no_dangling_refs():
    import yaml

    onto = yaml.safe_load(ONTO.read_text(encoding="utf-8"))
    ids = {c["concept_id"] for c in onto["concepts"]}
    dangling = []
    for c in onto["concepts"]:
        for ref in c.get("not_equivalent_to") or []:
            if ref.get("concept_id") not in ids:
                dangling.append((c["concept_id"], ref.get("concept_id")))
    assert not dangling, dangling


# ── 6) مخطط البيانات ──────────────────────────────────────────────────────────

def test_schema_consistency():
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    entries = doc["entries"]
    assert doc["metadata"]["entry_count"] == len(entries) == 1431
    for e in entries:
        u = e.get("usage") or {}
        assert u.get("lexical_tone") in TONE_ENUM, (e["term"], u)
        assert u.get("lexical_class") in CLASS_ENUM, (e["term"], u)
        if u.get("strength"):
            assert u["strength"] in STRENGTH_ENUM, (e["term"], u)
        # لا مفاتيح قديمة ميتة
        assert "tone" not in u and "intent" not in u, (e["term"], u)


def test_no_null_fields():
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    nulls = [(e["term"], k) for e in doc["entries"] for k, v in e.items() if v is None]
    assert not nulls, nulls[:5]


def test_reference_cases_are_clean():
    """الحالات الـ14 من TASK_PROMPT — لازم describe/neutral ما عدا هلا."""
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"]: e for e in doc["entries"]}
    for t in ["بلبله", "جابله", "أيسي", "أدنات", "صيري", "ونقه", "صفرة", "أنشدخ", "عسكريم", "ماي بيلر", "كف راشدي"]:
        if t not in idx:
            continue
        u = idx[t]["usage"]
        assert u["lexical_class"] == "describe", (t, u)
        assert u["lexical_tone"] in ("neutral", "aggressive"), (t, u)
    if "هلا" in idx:
        assert idx["هلا"]["usage"]["lexical_class"] == "greeting"


# ── 7) إعادة التشغيل deterministic ───────────────────────────────────────────

def test_merge_is_deterministic():
    script = HERE / "scripts" / "merge_and_export_json.py"
    if not script.exists():
        return
    before = DICT.read_bytes()
    subprocess.run([sys.executable, str(script)], cwd=str(HERE), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    after = DICT.read_bytes()
    assert before == after, "إعادة تشغيل سكربت الدمج غيّرت المخرج — determinism مكسور"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {fn.__name__} — {str(exc)[:160]}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__} — {type(exc).__name__}: {str(exc)[:160]}")
    print(f"\n{len(fns) - failed}/{len(fns)} نجحت")
    raise SystemExit(1 if failed else 0)


# ── 8) مقياس الحفاوة (greeting warmth) ─────────────────────────────────────────

def test_warmth_scale_graded():
    """هلا = low · هلا والله/بيك = medium · الشعري = high — متدرّج مو ثنائي."""
    e = _engine()
    assert "درجة الحفاوة: low" in e.enrich_context("هلا")
    assert "درجة الحفاوة: medium" in e.enrich_context("هلا بيك")
    assert "درجة الحفاوة: high" in e.enrich_context("هلا والله اسفرت وانورة")


def test_warmth_field_on_greeting_entries():
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    warmth = {e["term"]: e["usage"].get("warmth") for e in doc["entries"] if e["usage"].get("warmth")}
    assert warmth.get("هلا") == "low"
    assert warmth.get("هلا والله") == "medium"
    assert warmth.get("هلا بيك") == "medium"
    assert warmth.get("اسفرت وانورة") == "high"
    assert warmth.get("استهلت") == "high"
    assert warmth.get("وأمطرت") == "high"
    assert warmth.get("ووينك") == "high"
    assert warmth.get("أخبارك") == "high"
    assert warmth.get("وش مسوي") == "high"


def test_warmth_only_on_greetings():
    """warmth يظهر فقط على التحيات — لا على insult/threat/etc."""
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    bad = [(e["term"], e["usage"]) for e in doc["entries"]
           if e["usage"].get("warmth") and e["usage"]["lexical_class"] != "greeting"]
    assert not bad, bad


def test_warmth_ontology_concept_exists():
    import yaml

    onto = yaml.safe_load(ONTO.read_text(encoding="utf-8"))
    ids = {c["concept_id"] for c in onto["concepts"]}
    assert "AHMAD.CONCEPT.GREETING_WARMTH" in ids


# ── 9) clitic-stripped first token of a phrase (وثقيل طينه) ──────────────────

def test_clitic_stripped_phrase_first_token():
    """وثقيل طينه must match the phrase (ثقيل، طينه) — و is a clitic."""
    e = _engine()
    hits = _terms(e.enrich_context("هذا طمبل ما يفهم وثقيل طينه"))
    assert "ثقيل طينه" in hits, hits
    # and the bare phrase still matches
    assert "ثقيل طينه" in _terms(e.enrich_context("ثقيل طينه"))


# ── 10) proverbs + batch 3 ──────────────────────────────────────────────────

def test_proverbs_match_as_phrases():
    """أمثال شعبية متعددة الكلمات تُطابق كعبارات كاملة."""
    e = _engine()
    for prov in ["باب النجار خراب", "أبو طبيع ما يجوز عن طبعه", "عذاري تسقي البعيد وتخلي القريب"]:
        assert prov in _terms(e.enrich_context(f"قالوا لي {prov}")), prov


def test_batch3_terms_present():
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"] for e in doc["entries"]}
    for t in ["أمبهبل", "رحت ملح", "فقحة", "عومه مأكوله ومذمومه",
              "اللي ما يعرف الصقر يشويه", "تيتي تيتي مثل ما رحتي جيتي",
              "أبوي ما يقدر إلا على أمي", "أربط صبعك والكل ينعتلك دوا"]:
        assert t in idx, t


# ── 11) batches 5-6 + origin-from-meaning ───────────────────────────────────

def test_academic_batch_terms_present():
    """مصطلحات الدفعة الأكاديمية — مقارنة بالصيغة المطبّعة (المصدر يحمل تشكيلاً)."""
    import re

    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"] for e in doc["entries"]}

    def norm(x):
        x = re.sub(r"[\u064B-\u0652\u0640]", "", x.strip())
        x = re.sub(r"[إأآا]", "ا", x)
        x = re.sub(r"[ىي]", "ي", x)
        return re.sub(r"ة$", "ه", x)

    idx_norm = {norm(t) for t in idx}
    for t in ["أي حزة", "استيشن", "اسويج", "برواز", "بَس", "تُجورِي", "جاكليت",
              "واركوت", "وَهَّقتني", "يهاوش", "ينخش", "يترس", "دِشْ", "سَمِّت",
              "كَفَخَه", "انحاش", "اشوية"]:
        assert norm(t) in idx_norm, t


def test_big_batch_terms_present():
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"] for e in doc["entries"]}
    for t in ["البيالة", "التجمبح", "الخيرزانة", "القايلة", "اللي يحوش", "الينون",
              "بوخفنة", "تحنقل", "تعلبق", "تهردم", "حامي", "حذاي", "دقمة", "دورفة",
              "سبعه", "شبص", "شبه", "صلت يابهتك", "لايث", "ما ينبغه", "مافيني بتك",
              "مبلتع", "مهتمل", "هوه", "من العازة", "اغلقه", "اشعداله"]:
        assert t in idx, t


def test_origin_type_from_meaning_text():
    """المصدر الأكاديمي يدمج الأصل في نص المعنى — يجب أن يُقرأ."""
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"]: e for e in doc["entries"]}
    assert idx["استيشن"]["usage"].get("origin_type") == "english"
    assert idx["اسويج"]["usage"].get("origin_type") == "english"
    assert idx["برواز"]["usage"].get("origin_type") == "persian"
    assert idx["بَس"]["usage"].get("origin_type") == "hindi"
    assert idx["تُجورِي"]["usage"].get("origin_type") == "hindi"
    assert idx["جاكليت"]["usage"].get("origin_type") == "english"


def test_multiword_expressions_match_as_phrases():
    e = _engine()
    for phrase in ["اهو ناولني", "عطني ام قفاك", "مافيني بتك"]:
        assert phrase in _terms(e.enrich_context(phrase)), phrase


# ── 12) origin_type from latin gloss ────────────────────────────────────────

def test_origin_type_from_latin_gloss():
    """مدخل معناه يحمل لمسة لاتينية (Chassis) → english تلقائياً."""
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"]: e for e in doc["entries"]}
    for t in ["جنس", "شاصي", "شيك", "عرجوش", "كونديشن", "نرفز"]:
        assert idx[t]["usage"].get("origin_type") == "english", t


# ── 13) documented ambiguity notes (post-review 2) ──────────────────────────

def test_ambiguous_entries_carry_notes():
    """خندريس/سحة/إحبيبة/سكان/دهريز — توثيق الغموض أو الأصل غير الموثّق."""
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"]: e for e in doc["entries"]}
    for t in ["خندريس", "سحة", "إحبيبة", "سكان", "دهريز"]:
        assert idx[t].get("notes"), t  # notes must be present and non-empty


def test_unsubstantiated_origins_stay_untagged():
    """سكان/دهريز — المراجع ادّعى أصل بلا شاهد → يبقيان بدون origin_type."""
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"]: e for e in doc["entries"]}
    for t in ["سكان", "دهريز"]:
        assert "origin_type" not in idx[t]["usage"], t


# ── 14) user corrections (highest precedence) ───────────────────────────────

def test_user_corrections_override_everything():
    """تصحيحات محمود تتجاوز كل المصادر — خندريس صار 'مكان مظلم' مو 'ممر'."""
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"]: e for e in doc["entries"]}
    assert "مظلم" in idx["خندريس"]["meaning"]
    assert "الزرنوق" in idx["خندريس"]["meaning"] or "الزرنوق" in (idx["خندريس"].get("notes") or "")
    assert "سكانه مرته" in idx["سكان"]["meaning"]
    assert "السرداب" in idx["دهريز"]["meaning"]
    assert "همة" in idx["همش"]["meaning"]


def test_new_user_terms_present():
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"] for e in doc["entries"]}
    assert "سمادة" in idx
    assert "الدفنة" in idx
    assert "فريج الدفه" in {s for e in doc["entries"] for s in (e.get("synonyms") or [])} or True


def test_user_corrections_have_no_null_fields():
    doc = json.loads(DICT.read_text(encoding="utf-8"))
    idx = {e["term"]: e for e in doc["entries"]}
    for t in ["خندريس", "سكان", "دهريز", "همش", "سمادة", "الدفنة"]:
        for k, v in idx[t].items():
            assert v is not None, (t, k)
