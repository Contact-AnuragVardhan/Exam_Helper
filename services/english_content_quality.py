from __future__ import annotations

import re
from pathlib import Path

from .english_print_cleanup import (
    FURNITURE_RE,
    looks_like_retrieval_dump,
    normalize_options,
)
from .english_poetry_extract import poetry_plain_words, render_poetry_extract
from .english_scene_image import choose_scene, generate_scene_image
from .logger import get_logger
from .llm_client import chat_json, mock_mode


log = get_logger("english_quality")

Q3_INSTRUCTION = (
    "Read the following passage carefully and make notes on it using headings "
    "and sub-headings. Also provide a suitable title for your notes."
)
Q5_INSTRUCTION = "Write an essay on any ONE of the following topics."
Q6_INSTRUCTION = "Observe the picture below and describe the scene in about 60–75 words."
Q6_DIRECTION = "Describe the setting, people or objects, and the activities taking place."

Q5_FALLBACK_TOPICS = [
    "The value of kindness in everyday life",
    "A journey by train that you cannot forget",
    "Social media: a friend or a foe",
    "Cleanliness of our neighbourhood",
]

NOTE_DUP_RE = re.compile(
    r"make notes on it using headings|make a suitable note|provide a suitable title",
    re.I,
)

GLOSSARY_RES = [
    re.compile(r"ledge a narrow horizontal shelf.{0,80}", re.I),
    re.compile(r"herring a soft-finned sea fish", re.I),
    re.compile(r"\(to\) skim to move lightly.{0,80}", re.I),
    re.compile(r"upbraiding scolding", re.I),
    re.compile(r"\(to\) whet to sharpen", re.I),
    re.compile(r"derisively in a manner showing.{0,80}", re.I),
    re.compile(r"preening making an effort to maintain feathers", re.I),
    re.compile(r"\(to be\) besieged by to be surrounded.{0,60}", re.I),
    re.compile(r"amphitheatre a building without a roof.{0,120}", re.I),
    re.compile(r"draped covered \(with cloth\)", re.I),
    re.compile(r"locusts insects which fly in big swarms.{0,80}", re.I),
    re.compile(r"crest top of a hill", re.I),
    re.compile(r"wistfully longingly.{0,200}", re.I),
]

ACTIVITY_RES = [
    re.compile(
        r"(?:Think about who you will send the money|Fill out the Money Order|"
        r"Now complete the following statements|In addition to the sender|"
        r"The ‘Acknowledgement’|Space for Communication|Use a part of your pocket money|"
        r"See how your partner enjoys).{0,2200}?(?=Lencho had predicted|big drops of rain|$)",
        re.I | re.S,
    ),
    re.compile(r"A B Activity In Column A.{0,700}?from Column B\.", re.I | re.S),
    re.compile(r"\bActivity\s+\d+\..{0,400}", re.I),
]


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z']*", text or ""))


def apply_english_content_quality(exam: dict, out_dir: Path | None = None) -> dict:
    """Overlay: change only Q1, Q3, Q5, Q6, Q9(a), Q9(b)."""
    items = exam.get("questions") or []
    _apply_q1(items, exam.get("llm_usage"))
    _apply_q3(items)
    _apply_q5(items, exam.get("llm_usage"))
    _apply_q6(items, exam, out_dir)
    _apply_q9a(items)
    _apply_q9b(items)
    exam["questions"] = items
    return exam


def _items(items: list[dict], qn: int, slot=None) -> list[dict]:
    out = [q for q in items if int(q.get("question_number") or 0) == qn]
    if slot is not None:
        out = [q for q in out if (q.get("sub_slot") or "") == slot]
    return out


def _apply_q1(items: list[dict], usage) -> None:
    recs = _items(items, 1)
    if not recs:
        return
    passage = (recs[0].get("passage") or "").strip()
    wc = word_count(passage)
    supported = all(_mcq_supported(q, passage) for q in recs) if 120 <= wc <= 160 else False
    if 120 <= wc <= 160 and supported and not looks_like_retrieval_dump(passage):
        for q in recs:
            q["passage"] = passage
            q["extract"] = ""
        return
    passage, generated = _q1_passage_then_questions(recs, usage)
    for i, q in enumerate(recs):
        q["passage"] = passage
        q["extract"] = ""
        if i < len(generated):
            g = generated[i]
            q["question_text"] = g["question_text"]
            q["options"] = normalize_options(g["options"])
            q["answer_key"] = g["answer_key"]
        q["generation_reason"] = "content_quality_q1_passage_first"


def _q1_passage_then_questions(recs: list[dict], usage) -> tuple[str, list[dict]]:
    passage = ""
    if not mock_mode():
        try:
            data = chat_json(
                "You write original Grade 10 unseen English passages. Return JSON only.",
                "Write ONE original unseen passage of 130 to 150 words. School-appropriate. "
                "Include several concrete facts, named people or places, actions, and a clear outcome. "
                "Do not use First Flight literature. Return {\"passage\":\"...\"}.",
                usage_acc=usage,
            )
            cand = (data.get("passage") or "").strip()
            if 120 <= word_count(cand) <= 160 and not looks_like_retrieval_dump(cand):
                passage = cand
        except Exception as e:
            log.warning("Q1 passage LLM failed: %s", e)
    if not passage:
        passage = _Q1_FALLBACK_PASSAGE
    generated = []
    if not mock_mode() and passage:
        try:
            data = chat_json(
                "You write Grade 10 unseen-passage MCQs. Every answer must be stated in the passage. "
                "Return JSON only.",
                "PASSAGE:\n"
                + passage
                + "\n\nWrite exactly 5 MCQs. Each has question_text, options "
                "as [{\"label\":\"A\",\"text\":\"...\"}...D], and answer_key (A-D). "
                "Distractors plausible but clearly wrong from the passage. "
                "Return {\"items\":[...]} in order (i) to (v).",
                usage_acc=usage,
            )
            batch = data.get("items") or []
            if isinstance(batch, dict):
                batch = [batch]
            for raw in batch[:5]:
                opts = normalize_options(raw.get("options") or [])
                ans = str(raw.get("answer_key") or "A").strip()[:1].upper()
                if len(opts) == 4 and ans in "ABCD":
                    generated.append(
                        {
                            "question_text": (raw.get("question_text") or "").strip(),
                            "options": opts,
                            "answer_key": ans,
                        }
                    )
        except Exception as e:
            log.warning("Q1 questions LLM failed: %s", e)
    if len(generated) < 5 or not all(_mcq_supported({"question_text": g["question_text"], "options": g["options"], "answer_key": g["answer_key"]}, passage) for g in generated):
        generated = [dict(x) for x in _Q1_FALLBACK_QUESTIONS]
        passage = _Q1_FALLBACK_PASSAGE
    return passage, generated


_Q1_FALLBACK_PASSAGE = (
    "When the monsoon flooded the fields around Rampur last July, fourteen-year-old "
    "Meera thought the school year was lost. Water stood knee-deep in the lanes, and "
    "the old classroom roof leaked so badly that books on the lower shelves turned "
    "soft and grey. Instead of waiting, the village science club met under a banyan "
    "tree. They measured the rainfall, mapped the drains that were choked with plastic, "
    "and wrote to the panchayat. Within a fortnight, farmers and students cleared the "
    "blocked channels together. The club also built three simple rain gauges from "
    "discarded bottles so that the next flood could be predicted a day earlier. When "
    "school reopened, Meera’s report on the project was read aloud at assembly. The "
    "headmaster said the real lesson was not only science, but the habit of acting "
    "before a problem becomes a disaster. Several nearby villages have now asked the "
    "club to teach them the same method."
)

_Q1_FALLBACK_QUESTIONS = [
    {
        "question_text": "Why did Meera think the school year was lost?",
        "options": [
            {"label": "A", "text": "The monsoon flooded Rampur and damaged the classroom"},
            {"label": "B", "text": "The science club refused to meet"},
            {"label": "C", "text": "The panchayat closed the school forever"},
            {"label": "D", "text": "She wanted to work in the fields"},
        ],
        "answer_key": "A",
    },
    {
        "question_text": "Where did the village science club meet after the flood?",
        "options": [
            {"label": "A", "text": "In the leaking classroom"},
            {"label": "B", "text": "Under a banyan tree"},
            {"label": "C", "text": "At the panchayat office"},
            {"label": "D", "text": "In a nearby city library"},
        ],
        "answer_key": "B",
    },
    {
        "question_text": "What did the club write to the panchayat after mapping the drains?",
        "options": [
            {"label": "A", "text": "A request to shift the village"},
            {"label": "B", "text": "A complaint about the headmaster"},
            {"label": "C", "text": "They wrote after measuring rainfall and mapping choked drains"},
            {"label": "D", "text": "An invitation to a sports meet"},
        ],
        "answer_key": "C",
    },
    {
        "question_text": "What did the club build from discarded bottles?",
        "options": [
            {"label": "A", "text": "Three simple rain gauges"},
            {"label": "B", "text": "A new classroom roof"},
            {"label": "C", "text": "Plastic boats"},
            {"label": "D", "text": "Drinking-water tanks"},
        ],
        "answer_key": "A",
    },
    {
        "question_text": "What lesson did the headmaster say the project really taught?",
        "options": [
            {"label": "A", "text": "That floods cannot be predicted"},
            {"label": "B", "text": "That science is less important than sports"},
            {"label": "C", "text": "That nearby villages should close their schools"},
            {"label": "D", "text": "The habit of acting before a problem becomes a disaster"},
        ],
        "answer_key": "D",
    },
]


def _apply_q3(items: list[dict]) -> None:
    recs = _items(items, 3)
    for q in recs:
        q["section_heading"] = Q3_INSTRUCTION
        q["question_text"] = Q3_INSTRUCTION
        q["suppress_question_text"] = True


def _apply_q5(items: list[dict], usage) -> None:
    recs = _items(items, 5)
    if not recs:
        return
    q = recs[0]
    q["section_heading"] = Q5_INSTRUCTION
    topics = [str(t).strip() for t in (q.get("essay_topics") or []) if str(t).strip()]
    if len(topics) != 4 or _topics_too_similar(topics):
        extra = []
        stem = (q.get("question_text") or "").strip()
        if stem and not re.match(r"write an essay on any", stem, re.I):
            extra.append(_topic_from_stem(stem))
        topics = _four_distinct_topics(extra, usage)
    q["essay_topics"] = topics[:4]
    q["question_text"] = Q5_INSTRUCTION
    q["suppress_question_text"] = True
    q["marks"] = int(q.get("marks") or 5)
    q["counted_marks"] = int(q.get("counted_marks") if q.get("counted_marks") not in (None, "") else q.get("marks") or 5)


def _topic_from_stem(stem: str) -> str:
    t = re.sub(r"^write an essay on (?:the )?(?:topic )?(?:of )?(?:the )?", "", stem.strip(), flags=re.I)
    t = re.split(r"[.]", t, maxsplit=1)[0].strip(" .")
    return t[:80] if t else ""


def _topics_too_similar(topics: list[str]) -> bool:
    norms = [re.sub(r"[^a-z]+", "", t.lower()) for t in topics]
    for i, a in enumerate(norms):
        for b in norms[i + 1 :]:
            if a and b and (a in b or b in a or a[:12] == b[:12]):
                return True
    return False


def _four_distinct_topics(seed: list[str], usage) -> list[str]:
    topics = [t for t in seed if t]
    if not mock_mode():
        try:
            data = chat_json(
                "You write Grade 10 English essay prompts. Return JSON only.",
                "Give exactly 4 genuinely different essay topics suitable for Class 10. "
                "Varied themes (values, place/travel, media/technology, civic/environment). "
                "Short titles only. Return {\"topics\":[\"...\",\"...\",\"...\",\"...\"]}.",
                usage_acc=usage,
            )
            got = [str(t).strip() for t in (data.get("topics") or []) if str(t).strip()]
            if len(got) >= 4 and not _topics_too_similar(got[:4]):
                return got[:4]
        except Exception as e:
            log.warning("Q5 topic LLM failed: %s", e)
    for t in Q5_FALLBACK_TOPICS:
        if t not in topics:
            topics.append(t)
        if len(topics) == 4:
            break
    return topics[:4]


def _apply_q6(items: list[dict], exam: dict, out_dir: Path | None) -> None:
    recs = _items(items, 6)
    if not recs:
        return
    q = recs[0]
    q["section_heading"] = Q6_INSTRUCTION
    q["question_text"] = Q6_DIRECTION
    marks = int(q.get("marks") or 4)
    q["marks"] = marks
    q["counted_marks"] = int(q.get("counted_marks") if q.get("counted_marks") not in (None, "") else marks)
    scene = choose_scene(str(exam.get("exam_id") or exam.get("exam_name") or "english"))
    q["scene_id"] = scene
    q["picture_prompt"] = ""
    q["picture_image"] = ""
    q["q6_image_status"] = "FAILED"
    exam["q6_status"] = "FAILED"
    if out_dir is None:
        log.error("Q6 FAILED: no output directory for image asset")
        return
    dest = Path(out_dir) / "assets" / f"q6_{scene}.png"
    path = generate_scene_image(dest, scene_id=scene, seed=str(exam.get("exam_id") or scene))
    if path:
        q["picture_image"] = str(path)
        q["q6_image_status"] = "OK"
        exam["q6_status"] = "OK"
        exam["q6_image"] = str(path)
    else:
        log.error("Q6 FAILED: image asset was not created")


def _apply_q9a(items: list[dict]) -> None:
    recs = _items(items, 9, "a")
    if not recs:
        return
    lead = recs[0]
    title = lead.get("chapter_or_poem") or ""
    raw = lead.get("source_context") or lead.get("extract") or lead.get("passage") or ""
    rendered = render_poetry_extract(raw, title)
    body = poetry_plain_words(rendered)
    facts = _poetry_fact_bank(body)
    for i, q in enumerate(recs):
        q["extract"] = rendered
        q["passage"] = rendered
        q["kind"] = "poem"
        if i < len(facts):
            q["question_text"] = facts[i]["question_text"]
            q["options"] = normalize_options(facts[i]["options"])
            q["answer_key"] = facts[i]["answer_key"]
        elif not _mcq_supported(q, body):
            _replace_unsupported_poetry_mcq(q, body, rendered)


def _apply_q9b(items: list[dict]) -> None:
    recs = _items(items, 9, "b")
    if not recs:
        return
    lead = recs[0]
    title = lead.get("chapter_or_poem") or ""
    raw = _full_book_excerpt(lead.get("chapter_id")) or lead.get("source_context") or lead.get("extract") or ""
    extract = longer_book_prose_extract(raw, title)
    facts = _prose_fact_bank(extract)
    for i, q in enumerate(recs):
        q["extract"] = extract
        q["passage"] = extract
        q["kind"] = "prose"
        if i < len(facts):
            q["question_text"] = facts[i]["question_text"]
            q["options"] = normalize_options(facts[i]["options"])
            q["answer_key"] = facts[i]["answer_key"]
        elif not _mcq_supported(q, extract):
            _replace_unsupported_prose_mcq(q, extract)


def _full_book_excerpt(chapter_id: str | None) -> str:
    if not chapter_id:
        return ""
    try:
        from .english_book_importer import load_english_book_index

        index = load_english_book_index()
        for t in index.get("topics") or []:
            if t.get("chapter_id") == chapter_id and t.get("source_excerpt"):
                return t["source_excerpt"]
    except Exception:
        return ""
    return ""


def longer_book_prose_extract(raw: str, title: str = "") -> str:
    cleaned = clean_book_prose(raw, title)
    wc = word_count(cleaned)
    if 120 <= wc <= 180 and not looks_like_retrieval_dump(cleaned):
        return cleaned.strip()
    window = _word_window(cleaned, 120, 180)
    if 110 <= word_count(window) <= 190 and not looks_like_retrieval_dump(window):
        return window
    fallback = _canonical_prose_extract(title, cleaned)
    return fallback or window or cleaned[:1200].strip()


def clean_book_prose(raw: str, title: str = "") -> str:
    t = raw or ""
    t = re.sub(r"REPRINT 2026-27", " ", t, flags=re.I)
    t = re.split(
        r"\b(?:Oral Comprehension Check|Thinking about the Text|Thinking about the Poem|"
        r"Thinking about Language|What we have done|What you can do|BEFORE YOU READ|TO THE TEACHER)\b",
        t,
        maxsplit=1,
        flags=re.I,
    )[0]
    for rx in ACTIVITY_RES:
        t = rx.sub(" ", t)
    for rx in GLOSSARY_RES:
        t = rx.sub(" ", t)
    if title:
        t = re.sub(rf"\b{re.escape(title)}\b", " ", t)
    t = re.sub(r"\bTwo Stories about Flying\b", " ", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"just as\s+Lencho had predicted", "just as Lencho had predicted", t)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    keep = []
    for s in sentences:
        if looks_like_retrieval_dump(s) or FURNITURE_RE.search(s):
            continue
        if re.match(r"^(Activity|BEFORE YOU READ|Fill out)\b", s, re.I):
            continue
        if s.count("?") >= 2 and len(s) > 160:
            continue
        keep.append(s)
    return " ".join(keep).strip()


def _word_window(text: str, lo: int, hi: int) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]
    if not sentences:
        words = (text or "").split()
        return " ".join(words[:hi])
    best = ""
    for i in range(len(sentences)):
        acc = []
        for s in sentences[i:]:
            acc.append(s)
            joined = " ".join(acc)
            wc = word_count(joined)
            if lo <= wc <= hi:
                best = joined
                if wc >= lo + 15:
                    return joined
            if wc > hi:
                if not best:
                    best = joined
                break
    if best:
        return best
    words = (text or "").split()
    return " ".join(words[:hi])


def _canonical_prose_extract(title: str, cleaned: str) -> str:
    key = (title or "").lower()
    bank = {
        "a letter to god": (
            "It was during the meal that, just as Lencho had predicted, big drops of rain "
            "began to fall. In the north-east huge mountains of clouds could be seen "
            "approaching. The air was fresh and sweet. The man went out for no other reason "
            "than to have the pleasure of feeling the rain on his body, and when he returned "
            "he exclaimed, “These aren’t raindrops falling from the sky, they are new coins. "
            "The big drops are ten cent pieces and the little ones are fives.” With a "
            "satisfied expression he regarded the field of ripe corn with its flowers, draped "
            "in a curtain of rain. But suddenly a strong wind began to blow and along with "
            "the rain very large hailstones began to fall. For an hour the hail rained on the "
            "house, the garden, the hillside, the cornfield, on the whole valley. The field "
            "was white, as if covered with salt. Not a leaf remained on the trees. The corn "
            "was totally destroyed."
        ),
        "nelson mandela: long walk to freedom": (
            "TENTH May dawned bright and clear. For the past few days I had been pleasantly "
            "besieged by dignitaries and world leaders who were coming to pay their respects "
            "before the inauguration. The inauguration would be the largest gathering ever of "
            "international leaders on South African soil. The ceremonies took place in the "
            "lovely sandstone amphitheatre formed by the Union Buildings in Pretoria. For "
            "decades this had been the seat of white supremacy, and now it was the site of a "
            "rainbow gathering of different colours and nations for the installation of South "
            "Africa’s first democratic, non-racial government. On that lovely autumn day I "
            "was accompanied by my daughter Zenani. On the podium, Mr de Klerk was first "
            "sworn in as second deputy president. Then Thabo Mbeki was sworn in as first "
            "deputy president."
        ),
        "two stories about flying": (
            "THE young seagull was alone on his ledge. His two brothers and his sister had "
            "already flown away the day before. He had been afraid to fly with them. Somehow "
            "when he had taken a little run forward to the brink of the ledge and attempted "
            "to flap his wings he became afraid. The great expanse of sea stretched down "
            "beneath, and it was such a long way down — miles down. He felt certain that his "
            "wings would never support him; so he bent his head and ran away back to the "
            "little hole under the ledge where he slept at night. Even when each of his "
            "brothers and his little sister, whose wings were far shorter than his own, ran "
            "to the brink, flapped their wings, and flew away, he failed to muster up courage "
            "to take that plunge which appeared to him so desperate. His father and mother "
            "had come around calling to him shrilly, upbraiding him, threatening to let him "
            "starve on his ledge unless he flew away. But for the life of him he could not move."
        ),
    }
    for k, text in bank.items():
        if k in key:
            return text
    return ""


def _content_words(text: str) -> set[str]:
    stop = {
        "the", "and", "that", "this", "with", "from", "were", "was", "are", "for",
        "his", "her", "they", "them", "she", "him", "had", "have", "has", "not",
        "what", "when", "which", "into", "about", "their", "been", "does", "did",
        "poet", "poem", "extract", "passage", "according", "following", "below",
        "correct", "option", "choose",
    }
    return {w for w in re.findall(r"[a-z][a-z']+", (text or "").lower()) if len(w) > 3 and w not in stop}


def _answer_text(q: dict) -> str:
    ans = str(q.get("answer_key") or "").strip()
    lab = ans[:1].upper() if ans else ""
    for o in q.get("options") or []:
        if str(o.get("label") or "").upper() == lab:
            return str(o.get("text") or "")
    return ans


def _mcq_supported(q: dict, source: str) -> bool:
    src_words = _content_words(source)
    if not src_words:
        return False
    a_words = _content_words(_answer_text(q))
    if a_words and len(a_words & src_words) >= 1:
        return True
    return False


def _poetry_fact_bank(body: str) -> list[dict]:
    low = body.lower()
    facts = []
    if "dust of snow" in low and "hemlock" in low:
        facts.extend(
            [
                {
                    "question_text": "What does the poet say has given his heart a change of mood?",
                    "options": [
                        {"label": "A", "text": "The sound of thunder"},
                        {"label": "B", "text": "The dust of snow"},
                        {"label": "C", "text": "A song of a bird"},
                        {"label": "D", "text": "A walk in the sun"},
                    ],
                    "answer_key": "B",
                },
                {
                    "question_text": "From which tree did the crow shake the dust of snow?",
                    "options": [
                        {"label": "A", "text": "A maple tree"},
                        {"label": "B", "text": "A hemlock tree"},
                        {"label": "C", "text": "An oak tree"},
                        {"label": "D", "text": "A pine tree"},
                    ],
                    "answer_key": "B",
                },
                {
                    "question_text": "What did the falling dust of snow save?",
                    "options": [
                        {"label": "A", "text": "Some part of a day the poet had rued"},
                        {"label": "B", "text": "The hemlock tree from dying"},
                        {"label": "C", "text": "The crow from the cold"},
                        {"label": "D", "text": "The poet’s harvest"},
                    ],
                    "answer_key": "A",
                },
            ]
        )
    elif "desire" in low and "fire" in low:
        facts.extend(
            [
                {
                    "question_text": "Some say the world will end in fire. What is the other way mentioned?",
                    "options": [
                        {"label": "A", "text": "In ice"},
                        {"label": "B", "text": "In flood"},
                        {"label": "C", "text": "In darkness"},
                        {"label": "D", "text": "In wind"},
                    ],
                    "answer_key": "A",
                },
                {
                    "question_text": "After tasting desire, with whom does the speaker hold?",
                    "options": [
                        {"label": "A", "text": "Those who favour ice"},
                        {"label": "B", "text": "Those who favour fire"},
                        {"label": "C", "text": "Those who favour snow"},
                        {"label": "D", "text": "Those who favour hate"},
                    ],
                    "answer_key": "B",
                },
                {
                    "question_text": "What does the speaker say about ice?",
                    "options": [
                        {"label": "A", "text": "It is too weak for destruction"},
                        {"label": "B", "text": "It would never appear twice"},
                        {"label": "C", "text": "For destruction ice is also great and would suffice"},
                        {"label": "D", "text": "It stands only for desire"},
                    ],
                    "answer_key": "C",
                },
            ]
        )
    return facts


def _replace_unsupported_poetry_mcq(q: dict, body: str, rendered: str) -> None:
    low = body.lower()
    if "hemlock" in low:
        q["question_text"] = "From where did the crow shake the dust of snow?"
        q["options"] = normalize_options(
            [
                {"label": "A", "text": "A maple tree"},
                {"label": "B", "text": "A hemlock tree"},
                {"label": "C", "text": "An oak tree"},
                {"label": "D", "text": "A pine tree"},
            ]
        )
        q["answer_key"] = "B"
        return
    if "desire" in low and "fire" in low:
        q["question_text"] = "With whom does the speaker ‘hold’ after tasting desire?"
        q["options"] = normalize_options(
            [
                {"label": "A", "text": "Those who favour fire"},
                {"label": "B", "text": "Those who favour ice"},
                {"label": "C", "text": "Those who favour snow"},
                {"label": "D", "text": "Those who favour hate"},
            ]
        )
        q["answer_key"] = "A"
        return
    q["question_text"] = "Which detail is stated in the extract?"
    snippet = body.split()[:6]
    q["options"] = normalize_options(
        [
            {"label": "A", "text": " ".join(snippet) if snippet else "The printed lines"},
            {"label": "B", "text": "A scene that is not in the extract"},
            {"label": "C", "text": "A later chapter of the book"},
            {"label": "D", "text": "A glossary note from the textbook"},
        ]
    )
    q["answer_key"] = "A"


def _replace_unsupported_prose_mcq(q: dict, extract: str) -> None:
    facts = _prose_fact_bank(extract)
    used = (q.get("question_text") or "")[:20]
    for fact in facts:
        if fact["question_text"] != used:
            q["question_text"] = fact["question_text"]
            q["options"] = normalize_options(fact["options"])
            q["answer_key"] = fact["answer_key"]
            return


def _fill_missing_prose_mcqs(recs: list[dict], extract: str) -> None:
    facts = _prose_fact_bank(extract)
    used = {(q.get("question_text") or "").strip().lower() for q in recs}
    fi = 0
    for q in recs:
        if (q.get("question_text") or "").strip() and q.get("options"):
            continue
        while fi < len(facts) and facts[fi]["question_text"].lower() in used:
            fi += 1
        if fi >= len(facts):
            break
        fact = facts[fi]
        fi += 1
        q["question_text"] = fact["question_text"]
        q["options"] = normalize_options(fact["options"])
        q["answer_key"] = fact["answer_key"]
        used.add(fact["question_text"].lower())


def _prose_fact_bank(extract: str) -> list[dict]:
    low = extract.lower()
    facts = []
    if "lencho had predicted" in low or "big drops of rain" in low:
        facts.append(
            {
                "question_text": "What began to fall during the meal, just as Lencho had predicted?",
                "options": [
                    {"label": "A", "text": "Snow"},
                    {"label": "B", "text": "Big drops of rain"},
                    {"label": "C", "text": "A swarm of locusts"},
                    {"label": "D", "text": "Dry leaves"},
                ],
                "answer_key": "B",
            }
        )
    if "new coins" in low:
        facts.append(
            {
                "question_text": "What did Lencho say the raindrops were?",
                "options": [
                    {"label": "A", "text": "Frozen pearls only"},
                    {"label": "B", "text": "Tears of the sky"},
                    {"label": "C", "text": "New coins"},
                    {"label": "D", "text": "Grains of salt"},
                ],
                "answer_key": "C",
            }
        )
    if "hail" in low and ("destroyed" in low or "hailstones" in low):
        facts.append(
            {
                "question_text": "How did the rain change, and what happened to the corn?",
                "options": [
                    {"label": "A", "text": "The rain stopped and the fields stayed dry"},
                    {"label": "B", "text": "The rain became lighter and saved the flowers"},
                    {"label": "C", "text": "The rain turned into snow and covered the house"},
                    {"label": "D", "text": "The rain turned into hail and the corn was destroyed"},
                ],
                "answer_key": "D",
            }
        )
    if "north-east" in low and "clouds" in low:
        facts.append(
            {
                "question_text": "What could be seen approaching in the north-east?",
                "options": [
                    {"label": "A", "text": "A postman with a letter"},
                    {"label": "B", "text": "Huge mountains of clouds"},
                    {"label": "C", "text": "A flock of locusts"},
                    {"label": "D", "text": "A line of carts"},
                ],
                "answer_key": "B",
            }
        )
    if "union buildings" in low or "pretoria" in low:
        facts.append(
            {
                "question_text": "Where did the ceremonies take place?",
                "options": [
                    {"label": "A", "text": "In Johannesburg"},
                    {"label": "B", "text": "In the Union Buildings in Pretoria"},
                    {"label": "C", "text": "In Cape Town"},
                    {"label": "D", "text": "In Durban"},
                ],
                "answer_key": "B",
            }
        )
    if "young seagull" in low:
        facts.append(
            {
                "question_text": "Why was the young seagull alone on his ledge?",
                "options": [
                    {"label": "A", "text": "His brothers and sister had already flown away"},
                    {"label": "B", "text": "His parents had left the island"},
                    {"label": "C", "text": "He was hiding from a storm"},
                    {"label": "D", "text": "He was guarding the nest"},
                ],
                "answer_key": "A",
            }
        )
    if not facts:
        sent = [s.strip() for s in re.split(r"(?<=[.!?])\s+", extract) if s.strip()]
        if sent:
            facts.append(
                {
                    "question_text": "Which statement is true according to the extract?",
                    "options": [
                        {"label": "A", "text": sent[0][:110]},
                        {"label": "B", "text": "The extract describes a later textbook chapter"},
                        {"label": "C", "text": "The extract is only a glossary list"},
                        {"label": "D", "text": "The extract gives homework instructions"},
                    ],
                    "answer_key": "A",
                }
            )
    return facts


def _ensure_unique_stems(recs: list[dict]) -> None:
    seen = set()
    for q in recs:
        key = re.sub(r"[^\w]+", "", (q.get("question_text") or "").lower())
        if key and key in seen:
            q["question_text"] = (q.get("question_text") or "").rstrip("? ") + ", as stated in the extract?"
        seen.add(re.sub(r"[^\w]+", "", (q.get("question_text") or "").lower()))
