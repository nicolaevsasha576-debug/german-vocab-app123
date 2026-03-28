from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
VOCAB_PATH = DATA_DIR / "vocab.json"

NOW_TZ = timezone.utc
ARTICLES = ["der", "die", "das"]


def utc_now() -> datetime:
    return datetime.now(tz=NOW_TZ)


def dt_to_iso(dt: datetime) -> str:
    return dt.astimezone(NOW_TZ).isoformat()


def iso_to_dt(s: str) -> datetime:
    # Accept both "...Z" and "+00:00" style
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(NOW_TZ)


@dataclass
class Card:
    id: str
    de: str
    en: str  # Russian translation text (kept as "en" for data compatibility)
    article: str = ""
    notes: str = ""
    created_at: str = ""

    # SRS-ish fields
    due_at: str = ""
    interval_days: int = 0
    ease: float = 2.3
    reps: int = 0
    lapses: int = 0


def infer_article(text: str) -> str:
    token = (text.strip().split(" ", 1)[0] if text.strip() else "").lower()
    return token if token in ARTICLES else ""


def noun_without_article(text: str) -> str:
    clean = text.strip()
    token = (clean.split(" ", 1)[0] if clean else "").lower()
    if token in ARTICLES and " " in clean:
        return clean.split(" ", 1)[1].strip()
    return clean


def new_card(de: str, en: str, notes: str, article: str = "") -> Card:
    now = utc_now()
    card_id = f"{int(now.timestamp() * 1000)}-{random.randint(1000, 9999)}"
    due = now  # new cards are due immediately
    de_clean = de.strip()
    article_clean = article.strip().lower()
    if article_clean not in ARTICLES:
        article_clean = infer_article(de_clean)
    return Card(
        id=card_id,
        de=de_clean,
        en=en.strip(),
        article=article_clean,
        notes=notes.strip(),
        created_at=dt_to_iso(now),
        due_at=dt_to_iso(due),
        interval_days=0,
        ease=2.3,
        reps=0,
        lapses=0,
    )


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not VOCAB_PATH.exists():
        VOCAB_PATH.write_text(json.dumps({"cards": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cards() -> List[Card]:
    ensure_storage()
    try:
        raw = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
        cards_raw = raw.get("cards", [])
        cards: List[Card] = []
        for item in cards_raw:
            if not isinstance(item, dict):
                continue
            cards.append(Card(**item))
        return cards
    except Exception:
        return []


def save_cards(cards: List[Card]) -> None:
    ensure_storage()
    payload = {"cards": [asdict(c) for c in cards]}
    VOCAB_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_due(card: Card) -> datetime:
    if not card.due_at:
        return utc_now()
    try:
        return iso_to_dt(card.due_at)
    except Exception:
        return utc_now()


def is_due(card: Card, now: datetime) -> bool:
    return parse_due(card) <= now


def srs_grade(card: Card, quality: int, now: datetime) -> Card:
    """
    A small SM-2 inspired scheduler:
    - quality: 0..3 (Again, Hard, Good, Easy)
    """
    quality = max(0, min(3, quality))

    # Map to SM-2-ish q (0..5)
    q_map = {0: 2, 1: 3, 2: 4, 3: 5}
    q = q_map[quality]

    ease = max(1.3, card.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    reps = card.reps
    interval = card.interval_days
    lapses = card.lapses

    if quality == 0:
        lapses += 1
        reps = 0
        interval = 1
    else:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 3
        else:
            interval = max(1, int(round(interval * ease)))

    due = now + timedelta(days=interval)
    card.ease = float(round(ease, 2))
    card.reps = int(reps)
    card.interval_days = int(interval)
    card.lapses = int(lapses)
    card.due_at = dt_to_iso(due)
    return card


def sort_key_due_then_new(card: Card) -> Tuple[datetime, str]:
    return (parse_due(card), card.created_at or "")


def find_card(cards: List[Card], card_id: str) -> Optional[int]:
    for i, c in enumerate(cards):
        if c.id == card_id:
            return i
    return None


def pick_quiz_choices(cards: List[Card], correct_id: str, k: int = 4) -> List[Card]:
    correct = [c for c in cards if c.id == correct_id]
    if not correct:
        return []
    correct_card = correct[0]
    pool = [c for c in cards if c.id != correct_id and c.en.strip()]
    random.shuffle(pool)
    choices = [correct_card] + pool[: max(0, k - 1)]
    random.shuffle(choices)
    return choices


def grade_from_percent(percent: float) -> str:
    if percent >= 90:
        return "A (Excellent)"
    if percent >= 80:
        return "B (Very good)"
    if percent >= 70:
        return "C (Good)"
    if percent >= 60:
        return "D (Pass)"
    return "F (Needs more practice)"


def build_test_questions(cards: List[Card], count: int) -> List[Dict[str, Any]]:
    # Prioritize new words first (reps == 0), then fill from the rest.
    new_cards = [c for c in cards if c.reps == 0]
    old_cards = [c for c in cards if c.reps > 0]
    random.shuffle(new_cards)
    random.shuffle(old_cards)
    selected = (new_cards + old_cards)[:count]

    questions: List[Dict[str, Any]] = []
    for c in selected:
        choices = pick_quiz_choices(cards, c.id, k=4)
        if len(choices) < 2:
            continue
        questions.append(
            {
                "card_id": c.id,
                "choice_ids": [x.id for x in choices],
            }
        )
    return questions


def export_json(cards: List[Card]) -> str:
    payload = {"cards": [asdict(c) for c in cards]}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_json(text: str) -> Tuple[int, int]:
    """
    Returns (added, updated).
    Uses `id` for merge when present, otherwise creates a new card.
    """
    cards = load_cards()
    by_id: Dict[str, Card] = {c.id: c for c in cards}

    raw = json.loads(text)
    items = raw.get("cards", raw if isinstance(raw, list) else [])
    if not isinstance(items, list):
        return (0, 0)

    added = 0
    updated = 0
    now = utc_now()

    for item in items:
        if not isinstance(item, dict):
            continue
        de = str(item.get("de", "")).strip()
        # Accept both "en" and "ru" keys so old/new exports can be imported.
        en = str(item.get("en", item.get("ru", ""))).strip()
        if not de or not en:
            continue

        item_id = str(item.get("id", "")).strip()
        if item_id and item_id in by_id:
            # Update the existing card's text fields, keep scheduling fields
            existing = by_id[item_id]
            existing.de = de
            existing.en = en
            incoming_article = str(item.get("article", "")).strip().lower()
            if incoming_article in ARTICLES:
                existing.article = incoming_article
            elif not existing.article:
                existing.article = infer_article(de)
            existing.notes = str(item.get("notes", existing.notes or "")).strip()
            updated += 1
        else:
            incoming_article = str(item.get("article", "")).strip().lower()
            c = new_card(
                de,
                en,
                str(item.get("notes", "")).strip(),
                incoming_article if incoming_article in ARTICLES else infer_article(de),
            )
            # Best-effort import of scheduling fields if present
            for field in ("due_at", "created_at"):
                val = item.get(field)
                if isinstance(val, str) and val:
                    setattr(c, field, val)
            for field in ("interval_days", "reps", "lapses"):
                val = item.get(field)
                if isinstance(val, int):
                    setattr(c, field, val)
            val = item.get("ease")
            if isinstance(val, (int, float)):
                c.ease = float(val)
            # If due_at missing, make it due now
            if not c.due_at:
                c.due_at = dt_to_iso(now)
            cards.append(c)
            by_id[c.id] = c
            added += 1

    save_cards(cards)
    return (added, updated)


def reset_session_state() -> None:
    for k in [
        "study_card_id",
        "study_show_answer",
        "quiz_card_id",
        "quiz_choices",
        "quiz_answered",
        "quiz_feedback",
        "quiz_last_direction",
        "test_questions",
        "test_index",
        "test_score",
        "test_started",
        "test_finished",
        "test_direction",
        "test_size",
        "article_card_id",
        "article_feedback",
    ]:
        if k in st.session_state:
            del st.session_state[k]


st.set_page_config(page_title="German-Russian Vocab", page_icon="📚", layout="centered")

st.markdown(
    """
    <style>
    .stApp {
        background:
            linear-gradient(rgba(10, 25, 47, 0.55), rgba(15, 23, 42, 0.55)),
            url("https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?auto=format&fit=crop&w=2000&q=80");
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-attachment: fixed;
    }

    .block-container {
        background: rgba(255, 255, 255, 0.88);
        border: 1px solid rgba(255, 255, 255, 0.45);
        border-radius: 18px;
        padding-top: 1.2rem;
        padding-bottom: 1.5rem;
        backdrop-filter: blur(6px);
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.24);
    }

    div[data-testid="stMetricValue"] {
        color: #1e3a8a;
    }

    div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
        border-radius: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("German-Russian Vocab")
st.caption("Add words, study flashcards, quiz yourself, and review with a simple schedule.")

cards = load_cards()
now = utc_now()

due_cards = [c for c in cards if is_due(c, now)]
due_cards.sort(key=sort_key_due_then_new)

total = len(cards)
due = len(due_cards)

col_a, col_b, col_c = st.columns(3)
col_a.metric("Total words", total)
col_b.metric("Due now", due)
col_c.metric("New today", sum(1 for c in cards if (c.created_at and iso_to_dt(c.created_at).date() == now.date())))

tab_add, tab_study, tab_quiz, tab_test, tab_articles, tab_manage = st.tabs(
    ["Add", "Study", "Quiz", "Test", "Articles", "Manage"]
)

with tab_add:
    st.subheader("Add a new word")
    with st.form("add_form", clear_on_submit=True):
        article = st.selectbox("Article", ["(auto)", "der", "die", "das"], index=0)
        de = st.text_input("German (Deutsch)", placeholder="z.B. der Apfel")
        en = st.text_input("Russian (Russisch)", placeholder="например: яблоко")
        notes = st.text_area("Notes (optional)", placeholder="plural, example sentence, article, etc.")
        submitted = st.form_submit_button("Add")
    if submitted:
        if not de.strip() or not en.strip():
            st.error("Please enter both German and Russian.")
        else:
            chosen_article = "" if article == "(auto)" else article
            cards.append(new_card(de, en, notes, chosen_article))
            save_cards(cards)
            reset_session_state()
            st.success("Added.")

    st.divider()
    st.subheader("Import / Export")
    export_text = export_json(cards)
    st.download_button("Download vocab.json", data=export_text, file_name="vocab.json", mime="application/json")

    uploaded = st.file_uploader("Import a vocab.json", type=["json"])
    if uploaded is not None:
        try:
            added, updated = import_json(uploaded.read().decode("utf-8"))
            reset_session_state()
            st.success(f"Imported: {added} added, {updated} updated.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not import file: {e}")

with tab_study:
    st.subheader("Flashcards (due first)")

    if not cards:
        st.info("Add a few words first.")
    else:
        study_pool_mode = st.radio(
            "Study pool",
            ["Due now first", "All words"],
            key="study_pool_mode",
            horizontal=True,
        )
        if study_pool_mode == "All words":
            pool = sorted(cards, key=sort_key_due_then_new)
        else:
            pool = due_cards if due_cards else sorted(cards, key=sort_key_due_then_new)
        if "study_card_id" not in st.session_state:
            st.session_state.study_card_id = pool[0].id
            st.session_state.study_show_answer = True

        idx = find_card(cards, st.session_state.study_card_id)
        if idx is None:
            st.session_state.study_card_id = pool[0].id
            st.session_state.study_show_answer = True
            idx = find_card(cards, st.session_state.study_card_id)

        card = cards[idx] if idx is not None else pool[0]

        st.write(f"**German:** {card.de}")
        if card.notes:
            with st.expander("Notes"):
                st.write(card.notes)

        show = st.session_state.get("study_show_answer", False)
        if show:
            st.write(f"**Russian:** {card.en}")
        else:
            st.write("**Russian:** _(hidden)_")

        col1, col2, col3 = st.columns([1, 1, 2])
        if col1.button("Show / Hide"):
            st.session_state.study_show_answer = not st.session_state.study_show_answer
            st.rerun()

        if col2.button("Next card"):
            st.session_state.study_show_answer = True
            # rotate through pool
            ids = [c.id for c in pool]
            if card.id in ids:
                next_id = ids[(ids.index(card.id) + 1) % len(ids)]
            else:
                next_id = ids[0]
            st.session_state.study_card_id = next_id
            st.rerun()

        st.divider()
        st.caption("Grade this card (updates next review date):")
        g1, g2, g3, g4 = st.columns(4)
        if g1.button("Again"):
            cards[idx] = srs_grade(card, 0, now)
            save_cards(cards)
            st.session_state.study_show_answer = True
            st.rerun()
        if g2.button("Hard"):
            cards[idx] = srs_grade(card, 1, now)
            save_cards(cards)
            st.session_state.study_show_answer = True
            st.rerun()
        if g3.button("Good"):
            cards[idx] = srs_grade(card, 2, now)
            save_cards(cards)
            st.session_state.study_show_answer = True
            st.rerun()
        if g4.button("Easy"):
            cards[idx] = srs_grade(card, 3, now)
            save_cards(cards)
            st.session_state.study_show_answer = True
            st.rerun()

with tab_quiz:
    st.subheader("Multiple choice quiz")

    if len(cards) < 2:
        st.info("Add at least 2 words to quiz yourself.")
    else:
        direction = st.radio(
            "Quiz direction",
            ["🇩🇪➡️🇷🇺 German -> Russian", "🇷🇺➡️🇩🇪 Russian -> German"],
            key="quiz_direction",
            horizontal=True,
        )

        if "quiz_card_id" not in st.session_state:
            st.session_state.quiz_card_id = random.choice(cards).id
            st.session_state.quiz_choices = [c.id for c in pick_quiz_choices(cards, st.session_state.quiz_card_id, k=4)]
            st.session_state.quiz_answered = False
            st.session_state.quiz_feedback = None
            st.session_state.quiz_last_direction = direction

        if st.session_state.get("quiz_last_direction") != direction:
            st.session_state.quiz_card_id = random.choice(cards).id
            st.session_state.quiz_choices = [c.id for c in pick_quiz_choices(cards, st.session_state.quiz_card_id, k=4)]
            st.session_state.quiz_answered = False
            st.session_state.quiz_feedback = None
            st.session_state.quiz_last_direction = direction

        q_idx = find_card(cards, st.session_state.quiz_card_id)
        if q_idx is None:
            st.session_state.quiz_card_id = random.choice(cards).id
            st.session_state.quiz_choices = [c.id for c in pick_quiz_choices(cards, st.session_state.quiz_card_id, k=4)]
            st.session_state.quiz_answered = False
            st.session_state.quiz_feedback = None
            q_idx = find_card(cards, st.session_state.quiz_card_id)

        q_card = cards[q_idx] if q_idx is not None else random.choice(cards)
        if direction.startswith("🇩🇪"):
            st.write(f"**German:** {q_card.de}")
        else:
            st.write(f"**Russian:** {q_card.en}")
        if q_card.notes:
            with st.expander("Notes"):
                st.write(q_card.notes)

        choice_cards = []
        for cid in st.session_state.quiz_choices:
            i = find_card(cards, cid)
            if i is not None:
                choice_cards.append(cards[i])
        if q_card.id not in [c.id for c in choice_cards]:
            choice_cards = pick_quiz_choices(cards, q_card.id, k=4)

        if direction.startswith("🇩🇪"):
            st.write("Pick the Russian meaning:")
        else:
            st.write("Pick the German meaning:")
        for idx, c in enumerate(choice_cards):
            option_label = c.en if direction.startswith("🇩🇪") else c.de
            if st.button(option_label, key=f"quiz_option_{idx}_{c.id}"):
                st.session_state.quiz_answered = True
                if c.id == q_card.id:
                    # Auto-advance immediately after a correct answer.
                    st.session_state.quiz_card_id = random.choice(cards).id
                    st.session_state.quiz_choices = [
                        cc.id for cc in pick_quiz_choices(cards, st.session_state.quiz_card_id, k=4)
                    ]
                    st.session_state.quiz_answered = False
                    st.session_state.quiz_feedback = None
                    st.rerun()
                else:
                    correct_text = q_card.en if direction.startswith("🇩🇪") else q_card.de
                    st.session_state.quiz_feedback = ("error", f"Not quite. Correct answer: **{correct_text}**")

        feedback = st.session_state.get("quiz_feedback")
        if feedback:
            level, msg = feedback
            if level == "success":
                st.success(msg)
            else:
                st.error(msg)

        coln1, coln2 = st.columns(2)
        if coln1.button("New question"):
            st.session_state.quiz_card_id = random.choice(cards).id
            st.session_state.quiz_choices = [c.id for c in pick_quiz_choices(cards, st.session_state.quiz_card_id, k=4)]
            st.session_state.quiz_answered = False
            st.session_state.quiz_feedback = None
            st.rerun()

        if coln2.button("Mark as reviewed (Good)"):
            # Let quiz reinforce scheduling too
            i = find_card(cards, q_card.id)
            if i is not None:
                cards[i] = srs_grade(cards[i], 2, now)
                save_cards(cards)
                st.success("Scheduled next review.")

with tab_manage:
    st.subheader("All words")
    if not cards:
        st.info("No words yet.")
    else:
        search = st.text_input("Search", placeholder="Type German or Russian...")
        filtered = cards
        if search.strip():
            s = search.strip().lower()
            filtered = [c for c in cards if s in c.de.lower() or s in c.en.lower() or s in (c.notes or "").lower()]

        filtered.sort(key=lambda c: (c.de.lower(), c.en.lower()))

        st.write(f"Showing **{len(filtered)}** of **{len(cards)}**.")
        for c in filtered[:200]:
            with st.expander(f"{c.de}  →  {c.en}"):
                if c.article:
                    st.write(f"**Article:** {c.article}")
                st.write(f"**German:** {c.de}")
                st.write(f"**Russian:** {c.en}")
                if c.notes:
                    st.write(f"**Notes:** {c.notes}")
                due_dt = parse_due(c)
                st.write(f"**Due:** {due_dt.date().isoformat()}  (interval {c.interval_days}d, ease {c.ease}, reps {c.reps})")

                colx, coly, colz = st.columns(3)
                if colx.button("Reset schedule", key=f"reset_{c.id}"):
                    c.due_at = dt_to_iso(utc_now())
                    c.interval_days = 0
                    c.ease = 2.3
                    c.reps = 0
                    c.lapses = 0
                    save_cards(cards)
                    reset_session_state()
                    st.rerun()

                if coly.button("Delete", key=f"del_{c.id}"):
                    cards = [cc for cc in cards if cc.id != c.id]
                    save_cards(cards)
                    reset_session_state()
                    st.rerun()

                if colz.button("Make due now", key=f"due_{c.id}"):
                    c.due_at = dt_to_iso(utc_now())
                    save_cards(cards)
                    reset_session_state()
                    st.rerun()

        if len(filtered) > 200:
            st.warning("Showing first 200 results. Narrow your search to see more.")

with tab_articles:
    st.subheader("Articles Trainer")
    st.caption("Pick the correct article for each noun.")

    article_cards = [c for c in cards if c.article in ARTICLES or infer_article(c.de)]
    if not article_cards:
        st.info("No words with articles yet. Add words like 'der Baum' or set article in Add tab.")
    else:
        if "article_card_id" not in st.session_state:
            st.session_state.article_card_id = random.choice(article_cards).id
            st.session_state.article_feedback = None

        a_idx = find_card(cards, st.session_state.article_card_id)
        if a_idx is None:
            st.session_state.article_card_id = random.choice(article_cards).id
            st.session_state.article_feedback = None
            a_idx = find_card(cards, st.session_state.article_card_id)

        a_card = cards[a_idx] if a_idx is not None else random.choice(article_cards)
        correct_article = a_card.article if a_card.article in ARTICLES else infer_article(a_card.de)
        noun = noun_without_article(a_card.de)

        st.write(f"**Noun:** {noun}")
        st.write(f"**Russian:** {a_card.en}")

        c1, c2, c3 = st.columns(3)
        for col, art in zip([c1, c2, c3], ARTICLES):
            if col.button(art, key=f"article_pick_{a_card.id}_{art}"):
                if art == correct_article:
                    st.session_state.article_feedback = ("success", "Correct!")
                    st.session_state.article_card_id = random.choice(article_cards).id
                    st.rerun()
                else:
                    st.session_state.article_feedback = (
                        "error",
                        f"Not quite. Correct article: **{correct_article}**",
                    )

        fb = st.session_state.get("article_feedback")
        if fb:
            level, msg = fb
            if level == "success":
                st.success(msg)
            else:
                st.error(msg)

        if st.button("Next noun", key="article_next"):
            st.session_state.article_card_id = random.choice(article_cards).id
            st.session_state.article_feedback = None
            st.rerun()

with tab_test:
    st.subheader("Test")
    st.caption("Answer all questions and get a final grade.")

    if len(cards) < 4:
        st.info("Add at least 4 words to start a test.")
    else:
        if "test_size" not in st.session_state:
            st.session_state.test_size = min(10, len(cards))
        if "test_direction" not in st.session_state:
            st.session_state.test_direction = "🇩🇪➡️🇷🇺 German -> Russian"
        if "test_started" not in st.session_state:
            st.session_state.test_started = False
        if "test_finished" not in st.session_state:
            st.session_state.test_finished = False

        test_size = st.slider(
            "Number of questions",
            min_value=4,
            max_value=min(30, len(cards)),
            value=st.session_state.test_size,
            key="test_size",
        )
        st.radio(
            "Test direction",
            ["🇩🇪➡️🇷🇺 German -> Russian", "🇷🇺➡️🇩🇪 Russian -> German"],
            key="test_direction",
            horizontal=True,
        )

        if not st.session_state.test_started or st.session_state.test_finished:
            if st.button("Start test", type="primary"):
                questions = build_test_questions(cards, test_size)
                if len(questions) < 2:
                    st.warning("Not enough valid cards for a test yet.")
                else:
                    st.session_state.test_questions = questions
                    st.session_state.test_index = 0
                    st.session_state.test_score = 0
                    st.session_state.test_started = True
                    st.session_state.test_finished = False
                    st.rerun()

        if st.session_state.test_started and not st.session_state.test_finished:
            questions = st.session_state.get("test_questions", [])
            idx = st.session_state.get("test_index", 0)

            if idx >= len(questions):
                st.session_state.test_finished = True
                st.rerun()

            q = questions[idx]
            q_card_i = find_card(cards, q["card_id"])
            if q_card_i is None:
                st.session_state.test_index = idx + 1
                st.rerun()
            q_card = cards[q_card_i]

            st.progress((idx) / max(1, len(questions)), text=f"Question {idx + 1} / {len(questions)}")
            if st.session_state.test_direction.startswith("🇩🇪"):
                st.write(f"**German:** {q_card.de}")
                st.write("Pick the Russian meaning:")
            else:
                st.write(f"**Russian:** {q_card.en}")
                st.write("Pick the German meaning:")

            choice_cards: List[Card] = []
            for cid in q["choice_ids"]:
                cidx = find_card(cards, cid)
                if cidx is not None:
                    choice_cards.append(cards[cidx])
            if q_card.id not in [c.id for c in choice_cards]:
                choice_cards = pick_quiz_choices(cards, q_card.id, k=4)

            for opt_i, c in enumerate(choice_cards):
                label = c.en if st.session_state.test_direction.startswith("🇩🇪") else c.de
                if st.button(label, key=f"test_option_{idx}_{opt_i}_{c.id}"):
                    if c.id == q_card.id:
                        st.session_state.test_score = st.session_state.test_score + 1
                    st.session_state.test_index = idx + 1
                    if st.session_state.test_index >= len(questions):
                        st.session_state.test_finished = True
                    st.rerun()

        if st.session_state.test_started and st.session_state.test_finished:
            total_q = len(st.session_state.get("test_questions", []))
            score = int(st.session_state.get("test_score", 0))
            percent = (100.0 * score / total_q) if total_q else 0.0
            grade = grade_from_percent(percent)

            st.success("Test finished!")
            col1, col2, col3 = st.columns(3)
            col1.metric("Score", f"{score}/{total_q}")
            col2.metric("Percent", f"{percent:.1f}%")
            col3.metric("Grade", grade)

            if st.button("Restart test"):
                st.session_state.test_started = False
                st.session_state.test_finished = False
                st.session_state.test_questions = []
                st.session_state.test_index = 0
                st.session_state.test_score = 0
                st.rerun()

