"""Fixed question lists for the faithfulness evaluation (see PROTOCOL.md). Frozen after the first run."""

from __future__ import annotations

# Step 2, answerable: 17 held-out v3 questions (loaded by id) + three multi-step questions from golden_v0.
ANSWERABLE_V3 = True
ANSWERABLE_V0_IDS = ["x-001", "x-003", "nvda-10q-009"]

# Step 2, unanswerable: the corpus has no such company, period or fact. Correct behaviour is to refuse.
UNANSWERABLE = [
    "What was Tesla's total revenue in 2025?",
    "What was Microsoft Azure revenue growth last quarter?",
    "What was NVIDIA's total revenue in fiscal year 2019?",
    "How many employees did Apple have in 2015?",
    "What was JPMorgan's net income in 2010?",
    "What is NVIDIA's stock price today?",
    "What does Apple's latest 10-K say about its plans for a flying car?",
    "What dividend per share did NVIDIA pay in fiscal 2010?",
    "What did Apple's 2018 10-K say about tariffs on Chinese goods?",
    "What was Amazon's cloud segment operating income in the second quarter of 2026?",
]
