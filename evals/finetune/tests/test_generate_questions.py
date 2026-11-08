from evals.finetune.generate_questions import parse_response, sample_chunks, shares_run, water_fill


def test_water_fill_gives_small_groups_everything_and_splits_the_rest() -> None:
    q = water_fill({"a": 50, "b": 60, "c": 500, "d": 500}, 600)
    assert q["a"] == 50 and q["b"] == 60
    assert q["c"] == q["d"] == 245 and sum(q.values()) == 600


def test_water_fill_never_exceeds_group_size() -> None:
    assert water_fill({"a": 3, "b": 4}, 100) == {"a": 3, "b": 4}


def test_shares_run_detects_four_consecutive_words_only() -> None:
    passage = "the company recognizes revenue when control transfers to the customer"
    assert shares_run("When does control transfers to the customer happen", passage)
    assert not shares_run("How is revenue recognized upon delivery", passage)


def test_parse_response_handles_json_null_and_junk() -> None:
    assert parse_response('{"direct": "What is the tariff on chips?", "paraphrase": null}') == {
        "direct": "What is the tariff on chips?",
        "paraphrase": None,
    }
    assert parse_response("no json here") is None


def test_sample_chunks_is_deterministic_and_stratified() -> None:
    el = [{"id": i, "accession": "A" if i < 100 else "B"} for i in range(110)]
    s1, s2 = sample_chunks(el, 40), sample_chunks(el, 40)
    assert s1 == s2 and len(s1) == 40
    assert sum(c["accession"] == "B" for c in s1) == 10
