"""Independent semantic counterexamples for the 2026-10-14 query repair.

These tests use isolated Settings and pure planning functions. No production DB,
browser, remote model, or saved artifact is changed.
"""
from copy import deepcopy

import pytest

from hotpost.config import Settings
from hotpost.source_planning import enrich_plan
from hotpost.source_queries import (
    grounded_tiktok_noun_phrase,
    product_query_plan,
    tiktok_product_queries,
)
from hotpost.source_search.planner import grounded_actions
from hotpost.studio_automation import identify_subject


def generated_plan(tmp_path, caption, response, *, visual=None, speech=""):
    base = product_query_plan(caption, visual or [], [], {"speech": speech}, [])
    return enrich_plan(
        Settings(data_dir=tmp_path), base, caption, {"speech": speech},
        lambda *_: deepcopy(response),
    )


def model_response(name, quote, *, kind="recipe", source="caption", queries=None):
    return {
        "subject_kind": kind,
        "primary_subject": {"name": name, "source": source, "quote": quote},
        "queries": queries or [],
        "tiktok_queries": [],
    }


def contains_scoop(rows):
    return any("scooping" in row["query"] or "舀取" in row["query"]
               or "떠서" in row["query"] for row in rows)


def spoon_plan():
    return {"products": [{"ko": "국자", "en": "ladle", "zh": "汤勺",
                          "sources": ["caption"], "confidence": "high"}]}


def test_openclip_only_guess_stays_a_hypothesis_for_an_uncatalogued_recipe():
    visual = ["vegetable slicer kitchen gadget", "多功能切菜器 厨房神器"]
    plan = product_query_plan("바나나와 계란을 섞어 간식을 만들어요", visual, [], {}, [])
    assert not any("openclip" in p.get("sources", []) for p in plan["products"])
    assert plan.get("inferred_products"), "Preserve the visual guess without promoting it"
    assert not any("slicer" in q["query"] or "切菜器" in q["query"]
                   for q in plan["query_details"])
    assert visual == ["vegetable slicer kitchen gadget", "多功能切菜器 厨房神器"]


def test_recipe_semantics_cannot_promote_the_visual_tool(tmp_path):
    quote = "사과와 계란으로 간식을 만들어요"
    plan = generated_plan(
        tmp_path, quote + ". 반 티스푼만 넣으세요.",
        model_response("사과", quote),
        visual=["vegetable slicer kitchen gadget", "多功能切菜器 厨房神器"],
    )
    assert plan["primary_subject"]["name"] == "사과"
    assert not any("openclip" in p.get("sources", []) for p in plan["products"])
    assert not contains_scoop(grounded_actions(plan, plan["query_evidence"]))
    assert not any("slicer" in q["query"] or "切菜器" in q["query"]
                   for q in plan["query_details"])


def test_recipe_label_does_not_remove_an_explicitly_advertised_tool(tmp_path):
    caption = "이 채칼은 사과를 얇게 잘라줘요. 채칼로 사과 요리를 만들어요."
    plan = generated_plan(tmp_path, caption,
                          model_response("채칼", "이 채칼은 사과를 얇게 잘라줘요"))
    assert any(p.get("ko") == "채칼" and "caption" in p.get("sources", [])
               for p in plan["products"])
    assert plan["primary_subject"]["name"] == "채칼"


@pytest.mark.parametrize("name,source,quote", [
    ("시나몬", "caption", "이거 반 티스푼만 넣으세요"),
    ("사과", "caption", "사과를 구우세요"),  # quote absent from actual source
    ("사과", "speech", "사과와 계란"),  # source is caption, not speech
    ("기분 좋은 아침이 시작돼요", "caption", "기분 좋은 아침이 시작돼요"),
    ("댓글에 나도 남겨주세요", "caption", "댓글에 나도 남겨주세요"),
    ("3만 원대", "caption", "3만 원대"),
    ("아침이 달라졌어요", "caption", "아침이 달라졌어요"),
    ("쉽게 청소할 수 있어요", "caption", "쉽게 청소할 수 있어요"),
    ("Breakfast feels much better", "caption", "Breakfast feels much better"),
])
def test_primary_subject_requires_exact_noun_and_correct_source(tmp_path, name, source, quote):
    caption = ("사과와 계란. 이거 반 티스푼만 넣으세요. 기분 좋은 아침이 시작돼요. "
               "댓글에 나도 남겨주세요. 3만 원대. 아침이 달라졌어요. 쉽게 청소할 수 있어요. "
               "Breakfast feels much better")
    plan = generated_plan(tmp_path, caption, model_response(name, quote, source=source))
    assert not plan.get("primary_subject"), "A quote/intent label is not a validated subject"


@pytest.mark.parametrize("text", [
    "반 티스푼만 넣으세요", "1 스푼만 넣습니다", "두 큰술을 넣어요",
    "one teaspoon of salt", "add 1 tbsp milk", "半茶匙盐", "一汤匙牛奶",
    "스푼을 보관하세요", "숟가락 없이도 됩니다", "숟가락으로 떠먹지 마세요",
    "do not scoop with a spoon", "勺子放在抽屉里",
])
def test_measurement_noun_storage_and_negative_context_are_not_scooping(text):
    assert not contains_scoop(grounded_actions(spoon_plan(), {"caption": text}))


@pytest.mark.parametrize("text", [
    "숟가락으로 수프를 떠서 담아요", "국자로 국물을 떠서 담습니다",
    "scoop the soup with a spoon", "用勺子舀取汤",
])
def test_actual_scoop_verb_with_context_remains_available(text):
    assert contains_scoop(grounded_actions(spoon_plan(), {"caption": text}))


def test_measuring_spoon_product_identity_is_independent_of_scoop_action():
    caption = "계량스푼으로 재료의 양을 측정해요"
    assert grounded_tiktok_noun_phrase("measuring spoon", caption) == "measuring spoon"
    assert not contains_scoop(grounded_actions(spoon_plan(), {"caption": caption}))


@pytest.mark.parametrize("query,quote", [
    ("밥도그", "소풍 도시락 밥도그를 만들었어요"),
    ("rice dog", "밥도그"), ("米饭热狗", "밥도그"),
    ("sausage", "소시지를 넣어요"), ("香肠", "소시지"),
    ("apple", "사과를 썰어요"), ("苹果", "사과"),
    ("steam cleaner", "스팀청소기"), ("蒸汽清洁机", "스팀청소기"),
    ("핸디형 스팀청소기", "핸디형 스팀청소기"),
    ("handheld steam cleaner", "핸디형 스팀청소기"),
    ("로봇청소기", "로봇청소기"), ("measuring spoon", "계량스푼"),
])
def test_reviewed_food_and_general_object_noun_translations(query, quote):
    assert grounded_tiktok_noun_phrase(query, quote) == query


@pytest.mark.parametrize("query,quote", [
    ("corn dog", "밥도그"), ("vacuum cleaner", "스팀청소기"),
    ("red silicone ladle", "국자"), ("silver steam cleaner", "스팀청소기"),
    ("handheld steam cleaner", "스팀청소기"),
    ("cinnamon", "이거 반 티스푼만 넣어요"),
    ("apple pie", "사과와 계란을 섞어요"),
    ("국자로 냄비 바닥 긁기", "국자"),
    ("사과 레시피 원본 영상 자막 없는", "사과"),
])
def test_wrong_translation_hidden_ingredient_or_unobserved_modifier_is_rejected(query, quote):
    assert grounded_tiktok_noun_phrase(query, quote) == ""


def test_model_product_intent_cannot_bypass_noun_and_modifier_checks(tmp_path):
    caption = "스팀청소기로 청소합니다. 이거 반 티스푼."
    response = model_response("스팀청소기", "스팀청소기", kind="product")
    response["tiktok_queries"] = [
        {"query": "steam cleaner", "language": "en", "source": "caption", "quote": "스팀청소기"},
        {"query": "vacuum cleaner", "language": "en", "source": "caption", "quote": "스팀청소기"},
        {"query": "silver steam cleaner", "language": "en", "source": "caption", "quote": "스팀청소기"},
        {"query": "cinnamon", "language": "en", "source": "caption", "quote": "이거 반 티스푼"},
        {"query": "스팀청소기로 청소하기", "language": "ko", "source": "caption", "quote": "스팀청소기로 청소합니다"},
    ]
    plan = generated_plan(tmp_path, caption, response)
    queries = tiktok_product_queries(plan)
    assert "steam cleaner" in queries
    assert not any("vacuum" in q or "silver" in q or "cinnamon" in q or "청소하기" in q for q in queries)


@pytest.mark.parametrize("ingredient_en,ingredient_ko", [
    ("cinnamon", "시나몬"), ("vanilla", "바닐라"), ("baking soda", "베이킹소다"),
])
def test_non_tiktok_scene_queries_cannot_name_an_undisclosed_ingredient(tmp_path, ingredient_en, ingredient_ko):
    caption = "사과와 계란으로 만들어요. 이거 반 티스푼만 넣어주세요."
    response = model_response("사과", "사과와 계란", queries=[
        {"query": f"{ingredient_en} apple egg recipe", "language": "en", "intent": "recipe",
         "source": "caption", "quote": "이거 반 티스푼"},
        {"query": f"{ingredient_ko} 사과 계란 요리", "language": "ko", "intent": "recipe",
         "source": "caption", "quote": "이거 반 티스푼"},
    ])
    plan = generated_plan(tmp_path, caption, response)
    assert not any(ingredient_en in row["query"] or ingredient_ko in row["query"]
                   for row in plan["query_details"])


@pytest.mark.parametrize("caption,query", [
    ("쌀가루로 팬케이크를 만들어요", "rice flour recipe"),
    ("두유로 간식을 만들어요", "soy milk recipe"),
    ("코코넛 밀크와 계란으로 만들어요", "coconut milk egg recipe"),
])
def test_actual_compound_ingredients_are_not_rejected_as_unobserved_component(tmp_path, caption, query):
    from hotpost.source_planning import grounded_named_terms
    assert grounded_named_terms(query, {"caption": caption})
    response = model_response("", "", queries=[
        {"query": query, "language": "en", "intent": "recipe", "source": "caption", "quote": caption},
    ])
    plan = generated_plan(tmp_path, caption, response)
    assert any(row["query"] == query for row in plan["query_details"])


def test_absent_ingredient_is_not_converted_into_an_added_ingredient(tmp_path):
    caption = "설탕 없이 사과와 계란으로 만들어요"
    response = model_response("사과", "사과와 계란", queries=[
        {"query": "sugar apple egg recipe", "language": "en", "intent": "recipe",
         "source": "caption", "quote": caption},
        {"query": "sugar free apple egg recipe", "language": "en", "intent": "recipe",
         "source": "caption", "quote": caption},
    ])
    plan = generated_plan(tmp_path, caption, response)
    queries = [row["query"] for row in plan["query_details"]]
    assert "sugar free apple egg recipe" in queries
    assert "sugar apple egg recipe" not in queries


def test_validated_primary_subject_displaces_story_metadata_fallback():
    manifest = {
        "caption": "소풍 도시락으로 밥도그 하나 싸줬어요",
        "product_evidence": {"primary_subject": {"name": "밥도그", "source": "caption", "quote": "밥도그"}},
    }
    assert identify_subject(manifest, "엄마들이랑 티타임 중인데\n유치원에서 전화가 왔어요", "미확인") == "밥도그"


def test_uncatalogued_primary_subject_is_consumed_without_story_fallback():
    caption = "접이식 독서대를 소개합니다"
    subject = {"name": "접이식 독서대", "source": "caption", "quote": "접이식 독서대"}
    manifest = {"caption": caption, "product_evidence": {"primary_subject": subject}}
    assert identify_subject(manifest, "엄마들이랑 티타임 중인데", "미확인") == "접이식 독서대"


def test_uncatalogued_reviewed_screen_subject_crosses_the_real_manifest_boundary():
    text = "실제로 사용한 접이식 독서대"
    manifest = {
        "caption": "댓글에 나도 남겨주세요",
        "product_evidence": {
            "primary_subject": {"name": "접이식 독서대", "source": "screen_text", "quote": text},
            "query_evidence": {"screen_text": text},
        },
    }
    assert "screen_text" not in manifest
    assert identify_subject(manifest, "", "미확인") == "접이식 독서대"


def test_forged_primary_subject_does_not_promote_a_hidden_ingredient():
    manifest = {"caption": "이거 반 티스푼만 넣어주세요",
                "product_evidence": {"primary_subject": {"name": "시나몬", "source": "caption", "quote": "이거 반 티스푼"}}}
    assert identify_subject(manifest, "", "미확인") == "미확인"


def test_unidentified_subject_does_not_become_an_advertising_story():
    subject = identify_subject({"caption": "댓글에 나도 남겨주세요"},
                               "엄마들이랑 티타임 중인데\n유치원에서 전화가 왔어요", "미확인")
    assert subject == "미확인"
