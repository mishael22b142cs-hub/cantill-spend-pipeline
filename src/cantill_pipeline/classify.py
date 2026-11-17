"""Classify every included line into the company's category tree, to its
lowest level, with a confidence from 0 to 1.

Two layers, matching the brief's "must also work with zero labels" rule:

  - Zero-shot (always available, needs only the taxonomy file): build one
    text blob per leaf category by concatenating its level names, TF-IDF
    vectorize both that tree corpus and every line's cleaned text (word
    n-grams for lexical overlap, char n-grams for abbreviation/typo
    tolerance), and assign the leaf with the highest cosine similarity.
    This is the only layer used for an unseen tree (company C) and for the
    "classify A from its tree alone" validation.

  - Supervised (only when a labelled training set is supplied for this
    company - labels_A, seed_labels_B): a TF-IDF + logistic-regression text
    classifier trained on (line text -> leaf). Used to boost accuracy on the
    companies we do have labels for; never required.

No category or company name appears in this file - only in the taxonomy csv
and the labels passed in at runtime.
"""
from __future__ import annotations

import csv
import re
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity

_LEVEL_COL_RE = re.compile(r"category_l(\d+)", re.IGNORECASE)


def load_taxonomy(path: str) -> list[tuple[str, ...]]:
    """Returns a list of leaf paths, each a tuple of level names (no blanks),
    e.g. ("Direct Materials", "Aluminium", "Ingot & Metal Premium")."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        level_cols: list[tuple[int, str]] = []
        for col in reader.fieldnames or []:
            m = _LEVEL_COL_RE.fullmatch(col.strip())
            if m:
                level_cols.append((int(m.group(1)), col))
        level_cols.sort()
        leaves = []
        for row in reader:
            path_values = []
            for _, col in level_cols:
                val = (row.get(col) or "").strip()
                if not val:
                    break
                path_values.append(val)
            if path_values:
                leaves.append(tuple(path_values))
    # de-duplicate while preserving order
    seen = set()
    unique_leaves = []
    for leaf in leaves:
        if leaf not in seen:
            seen.add(leaf)
            unique_leaves.append(leaf)
    return unique_leaves


_NOISE_RE = re.compile(r"[^a-z0-9 ]")


def _clean_text(text: str) -> str:
    text = (text or "").lower()
    text = _NOISE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


class ZeroShotClassifier:
    def __init__(self, leaves: list[tuple[str, ...]]):
        self.leaves = leaves
        leaf_texts = [_clean_text(" ".join(leaf)) for leaf in leaves]
        self.word_vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        self.char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
        self.leaf_word_matrix = self.word_vec.fit_transform(leaf_texts)
        self.leaf_char_matrix = self.char_vec.fit_transform(leaf_texts)

    def score_all(self, texts: list[str]) -> np.ndarray:
        cleaned = [_clean_text(t) for t in texts]
        word_q = self.word_vec.transform(cleaned)
        char_q = self.char_vec.transform(cleaned)
        word_sim = cosine_similarity(word_q, self.leaf_word_matrix)
        char_sim = cosine_similarity(char_q, self.leaf_char_matrix)
        return np.maximum(word_sim, char_sim)

    def predict(self, texts: list[str]) -> list[tuple[tuple[str, ...], float]]:
        sims = self.score_all(texts)
        results = []
        for row in sims:
            idx = int(np.argmax(row))
            results.append((self.leaves[idx], float(row[idx])))
        return results


class SupervisedClassifier:
    def __init__(self, texts: list[str], leaves: list[tuple[str, ...]]):
        self.leaf_by_label = {"|||".join(leaf): leaf for leaf in leaves}
        labels = ["|||".join(leaf) for leaf in leaves]
        cleaned = [_clean_text(t) for t in texts]
        self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        X = self.vec.fit_transform(cleaned)
        self.model = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.model.fit(X, labels)

    def predict(self, texts: list[str]) -> list[tuple[tuple[str, ...], float]]:
        cleaned = [_clean_text(t) for t in texts]
        X = self.vec.transform(cleaned)
        probs = self.model.predict_proba(X)
        classes = self.model.classes_
        results = []
        for row in probs:
            idx = int(np.argmax(row))
            label = classes[idx]
            results.append((self.leaf_by_label[label], float(row[idx])))
        return results


def classify_records(
    texts: list[str],
    leaves: list[tuple[str, ...]],
    train_texts: list[str] | None = None,
    train_leaves: list[tuple[str, ...]] | None = None,
    supervised_floor: float = 0.15,
) -> list[tuple[tuple[str, ...], float, str]]:
    """Returns [(leaf_path, confidence, mode)] per text, one of mode in
    {"zero_shot", "supervised"}. Pass train_texts=None (or omit) to force
    pure zero-shot - the code path used for company C and for the
    hidden-labels validation on A."""
    zero_shot = ZeroShotClassifier(leaves)
    zs_preds = zero_shot.predict(texts)

    if not train_texts or not train_leaves:
        return [(leaf, score, "zero_shot") for leaf, score in zs_preds]

    supervised = SupervisedClassifier(train_texts, train_leaves)
    sup_preds = supervised.predict(texts)

    results = []
    for (zs_leaf, zs_score), (sup_leaf, sup_score) in zip(zs_preds, sup_preds):
        if sup_score >= supervised_floor:
            results.append((sup_leaf, sup_score, "supervised"))
        else:
            results.append((zs_leaf, zs_score, "zero_shot"))
    return results
