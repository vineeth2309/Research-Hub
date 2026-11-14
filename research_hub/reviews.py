"""People's reviews of the samples of an eval set.

A review is about the sample, not about a run, so it counts for every run on the set, today's and tomorrow's. It is
appended and never edited: a later review of the same sample is the current one and the earlier ones stay as history.
Only people write reviews; agents read them. Nothing is written back to the labels, facts or datasets.
"""

from __future__ import annotations

import json

from .core import Forbidden, HubError, NotFound, choice, now, number
from .datasets import _mask
from .evals import NEGATIVES

REVIEW_CATEGORIES = ("critical defect", "graded defect", "unsure")  # unsure: leave the sample out of scoring
REVIEW_DIFFICULTIES = ("easy", "borderline", "tough")
UNSURE = "unsure"
MAX_SHOWN = 20_000


def _text(row) -> dict:
    return {"class": row["cls"], "severity": row["severity"], "category": row["category"], "difficulty": row["difficulty"],
            "bad_image": bool(row["bad_image"]), "comment": row["comment"], "reviewer": row["reviewer"],
            "created": row["created"], "confirmed": bool(row["confirmed"])}


def _is_review(row) -> bool:
    """A review with every field empty takes the review back."""
    return bool(row["cls"] or row["severity"] is not None or row["category"] or row["difficulty"] or row["bad_image"]
                or row["comment"])


class Reviews:
    @staticmethod
    def _review_options(conn, project) -> dict:
        """What a review can say, from the project's settings["review"] over the defaults."""
        row = conn.execute("SELECT settings FROM projects WHERE slug=?", (project,)).fetchone()
        wanted = (json.loads(row[0]) if row else {}).get("review") or {}
        lists = {k: [str(v)[:60] for v in wanted[k]][:12] if isinstance(wanted.get(k), list) and wanted[k] else list(default)
                 for k, default in (("categories", REVIEW_CATEGORIES), ("difficulties", REVIEW_DIFFICULTIES))}
        return {**lists, "label_class_fact": str(wanted.get("label_class_fact") or ""),
                "label_severity_fact": str(wanted.get("label_severity_fact") or "")}

    def review_sample(self, actor, project, eval_set, sample, data) -> dict:
        """Append a review of one sample; returns it as the sample's current review."""
        if actor.get("kind") != "human":
            raise Forbidden("only people write reviews; agents read them")
        if not isinstance(data, dict):
            raise HubError("a review is an object")
        with self.connect(write=True) as conn:
            set_id = self._set_id(conn, project, eval_set)
            item = conn.execute("SELECT id FROM eval_items WHERE set_id=? AND sample=?", (set_id, sample)).fetchone()
            if not item:
                raise NotFound(f"{sample} is not in {eval_set}")
            options = self._review_options(conn, project)
            severity = number(data.get("severity"), "severity")
            if severity is not None and not 0 <= severity <= 10:
                raise HubError("severity is a number from 0 to 10")
            category, difficulty = str(data.get("category") or ""), str(data.get("difficulty") or "")
            if category:
                choice(category, options["categories"], "category")
            if difficulty:
                choice(difficulty, options["difficulties"], "difficulty")
            shown = data.get("shown") or {}
            if not isinstance(shown, dict) or len(json.dumps(shown)) > MAX_SHOWN:
                raise HubError(f"shown is the label and the runs' calls on screen, at most {MAX_SHOWN} characters")
            row = {"cls": str(data.get("class") or "")[:200], "severity": severity, "category": category,
                   "difficulty": difficulty, "bad_image": 1 if data.get("bad_image") else 0,
                   "comment": str(data.get("comment") or "").strip()[:5000], "reviewer": actor["name"], "created": now(),
                   "confirmed": 1 if data.get("confirmed") else 0}
            conn.execute("INSERT INTO eval_reviews(set_id, item, reviewer, created, cls, severity, category, difficulty, "
                         "bad_image, comment, confirmed, shown) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         (set_id, item[0], row["reviewer"], row["created"], row["cls"], severity, category, difficulty,
                          row["bad_image"], row["comment"], row["confirmed"], json.dumps(shown)))
            self._event(conn, actor["name"], "review", f"sample:{eval_set}", f"reviewed {sample[:120]}", project)
        return {"sample": sample, "review": _text(row) if _is_review(row) else None}

    def reviews_list(self, project, eval_set, since=None, history=False, limit=100_000, sample=None) -> dict:
        """The current review of every reviewed sample, or every review with history, newest last. `sample` narrows
        it to one sample."""
        with self.connect() as conn:
            set_id = self._set_id(conn, project, eval_set)
            where = "r.set_id=?" + ("" if history else " AND r.id IN (SELECT MAX(id) FROM eval_reviews WHERE set_id=? "
                                                       "GROUP BY item)")
            args = [set_id] if history else [set_id, set_id]
            if since:
                where += " AND r.created>?"
                args.append(str(since))
            if sample:
                where += " AND i.sample=?"
                args.append(str(sample))
            out = []
            for r in conn.execute(f"SELECT r.*, i.sample FROM eval_reviews r JOIN eval_items i ON i.id=r.item WHERE {where} "
                                  "ORDER BY r.id LIMIT ?", (*args, min(int(limit), 200_000))):
                if history or _is_review(r):
                    out.append({"sample": r["sample"], **_text(r), "shown": json.loads(r["shown"])})
            return {"set": eval_set, "options": self._review_options(conn, project), "history": bool(history),
                    "reviews": out}

    def _review_state(self, conn, set_id, rec) -> dict:
        """The current reviews lined up with the set's samples, with a mask per field value; kept while unchanged."""
        count, newest = conn.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM eval_reviews WHERE set_id=?", (set_id,)).fetchone()
        size = len(rec["ids"])

        def build():
            by_pos, fields = {}, {k: {} for k in ("class", "category", "difficulty", "reviewer")}
            bad, scorable, negative = [], [], []
            for r in conn.execute("SELECT * FROM eval_reviews WHERE set_id=? AND id IN (SELECT MAX(id) FROM eval_reviews "
                                  "WHERE set_id=? GROUP BY item)", (set_id, set_id)):
                pos = rec["at"].get(r["item"])
                if pos is None or not _is_review(r):
                    continue
                review = _text(r)
                by_pos[pos] = review
                for key in fields:
                    if review[key]:
                        fields[key].setdefault(review[key], []).append(pos)
                if review["bad_image"]:
                    bad.append(pos)
                elif review["class"] and review["category"] != UNSURE:  # a class to score against
                    scorable.append(pos)
                    if review["class"].lower() in NEGATIVES:
                        negative.append(pos)
            return {"by_pos": by_pos, "reviewed": _mask(by_pos, size), "bad": _mask(bad, size),
                    "scorable": _mask(scorable, size), "negative": _mask(negative, size),
                    "fields": {k: {v: _mask(p, size) for v, p in vals.items()} for k, vals in fields.items()},
                    "severity": {p: r["severity"] for p, r in by_pos.items() if r["severity"] is not None}}
        return self._summary_cache().get((set_id, "reviews", count, newest, size), lambda s: len(s["by_pos"]) * 400 + 1000, build)
