import json

import pytest

from greenpulse_ai import Settings, build_service
from greenpulse_ai.agents.profile import PlantProfileAgent
from greenpulse_ai.plant_library import PlantLibrary
from greenpulse_ai.plant_profiles import checkpoint, get_profile
from greenpulse_ai.schemas import PlantCareProfile

from conftest import FakeLLM, reading

ALOE = {"moisture": (10, 35), "temperature": (15, 32), "humidity": (20, 60)}


# --------------------------------------------------------------------------- checkpoint


def test_checkpoint_passes_sensible_ranges_unchanged():
    assert checkpoint(ALOE) == (ALOE, [])


def test_checkpoint_fixes_impossible_ranges_and_says_what_changed():
    fixed, notes = checkpoint({"moisture": (60, 120), "temperature": (30, 18), "humidity": (50, 52)})
    assert fixed == {"moisture": (60, 95), "temperature": (18, 30), "humidity": (50, 65)}
    assert len(notes) == 3
    assert notes[0].startswith("Soil moisture: 60-120% adjusted to 60-95%")


# --------------------------------------------------------------------------- library


def test_added_plants_and_device_choices_are_saved(tmp_path):
    path = tmp_path / "plants.json"
    library = PlantLibrary(path, "pothos")
    aloe = library.add("Aloe Vera", ALOE, "Water when the soil is fully dry.", "Aloe vera", "ai")
    assert aloe.key == "aloe-vera" and aloe.source == "ai"
    assert library.add("Aloe vera", ALOE).key == "aloe-vera-2"  # names may repeat; keys may not

    assert library.profile_for("greenpulse-01").key == "pothos"  # the default until chosen
    library.assign("greenpulse-01", "aloe-vera")

    reopened = PlantLibrary(path, "pothos")
    assert reopened.profile_for("greenpulse-01") == aloe
    assert json.loads(path.read_text(encoding="utf-8"))["devices"] == {"greenpulse-01": "aloe-vera"}


def test_deleting_a_plant_moves_its_devices_back_to_the_default(tmp_path):
    library = PlantLibrary(tmp_path / "plants.json", "pothos")
    library.add("Aloe Vera", ALOE)
    library.assign("d1", "aloe-vera")
    assert library.delete("aloe-vera") == ["d1"]
    assert library.profile_for("d1").key == "pothos"


def test_built_in_plants_cannot_be_changed_or_deleted(tmp_path):
    library = PlantLibrary(tmp_path / "plants.json")
    with pytest.raises(PermissionError):
        library.update("pothos", "Pothos", ALOE)
    with pytest.raises(PermissionError):
        library.delete("snake_plant")
    with pytest.raises(KeyError):
        library.assign("d1", "no-such-plant")


def test_ranges_that_fail_the_checkpoint_are_not_saved(tmp_path):
    library = PlantLibrary(tmp_path / "plants.json")
    with pytest.raises(ValueError, match="Soil moisture"):
        library.add("Bog plant", {**ALOE, "moisture": (80, 100)})
    assert len(library.profiles()) == 4


def test_an_unreadable_file_leaves_the_built_in_plants(tmp_path):
    path = tmp_path / "plants.json"
    path.write_text("{not json", encoding="utf-8")
    assert [p.key for p in PlantLibrary(path).profiles()] == ["pothos", "snake_plant", "peace_lily", "generic"]


# --------------------------------------------------------------------------- Plant Profile Agent


def care(**changes) -> PlantCareProfile:
    values = dict(
        recognised=True,
        common_name="Aloe Vera",
        scientific_name="Aloe vera",
        soil_moisture_min=10,
        soil_moisture_max=35,
        temperature_min=15,
        temperature_max=32,
        humidity_min=20,
        humidity_max=60,
        care_notes="Water deeply, then let the soil dry out completely.",
    )
    return PlantCareProfile(**{**values, **changes})


def test_llm_draft_for_a_named_plant():
    llm = FakeLLM({PlantCareProfile: care()})
    draft = PlantProfileAgent(llm, "groq:test", "Colombo, LK").draft("  aloe   vera ")

    assert draft.name == "Aloe Vera" and draft.scientific_name == "Aloe vera"
    assert draft.moisture == (10, 35) and draft.source == "llm" and draft.model == "groq:test"
    assert draft.recognised and draft.checks == [] and draft.note == ""
    prompt = llm.prompts[PlantCareProfile][0]
    assert "Colombo, LK" in prompt[0].content
    assert prompt[1].content == "Plant name: aloe vera"


def test_the_checkpoint_corrects_the_llm():
    llm = FakeLLM({PlantCareProfile: care(soil_moisture_min=40, soil_moisture_max=140, humidity_min=70, humidity_max=30)})
    draft = PlantProfileAgent(llm).draft("Aloe vera")
    assert draft.moisture == (40, 95) and draft.humidity == (30, 70)
    assert [c.split(":")[0] for c in draft.checks] == ["Soil moisture", "Humidity"]


def test_an_unknown_name_is_flagged():
    llm = FakeLLM({PlantCareProfile: care(recognised=False, common_name="Blorp", scientific_name="")})
    draft = PlantProfileAgent(llm).draft("Blorp")
    assert not draft.recognised and "didn't recognise" in draft.note


def test_without_an_llm_known_names_and_plant_kinds_still_work():
    agent = PlantProfileAgent()
    snake = agent.draft("snake plant")
    assert snake.name == "Snake Plant" and snake.moisture == get_profile("snake_plant").moisture and snake.source == "rules"

    cactus = agent.draft("Golden barrel cactus")
    assert cactus.moisture == (10, 35) and cactus.recognised

    unknown = agent.draft("Mystery shrub")
    assert unknown.moisture == get_profile("generic").moisture and not unknown.recognised
    assert unknown.name == "Mystery shrub"


def test_llm_failure_falls_back_to_the_rules():
    draft = PlantProfileAgent(FakeLLM({PlantCareProfile: RuntimeError("timeout")})).draft("Money plant")
    assert draft.source == "rules-fallback" and draft.name == "Pothos (Money Plant)"
    assert draft.note.startswith("The AI couldn't be reached.")


# --------------------------------------------------------------------------- the analysis follows the plant


def test_each_device_is_judged_against_its_own_plant():
    snake, pothos = get_profile("snake_plant"), get_profile("pothos")
    service = build_service(Settings(offline=True), None, profile_for=lambda d: snake if d == "succulent-shelf" else pothos)

    # 25 % soil moisture: dry for a pothos (35-65 %), fine for a snake plant (15-40 %).
    for_pothos = service.handle_reading(reading(moisture=25.0, device_id="kitchen"))
    for_snake = service.handle_reading(reading(moisture=25.0, device_id="succulent-shelf"))

    assert for_pothos.environment.plant == "Pothos (Money Plant)" and for_pothos.priority == "high"
    assert for_snake.environment.plant == "Snake Plant" and for_snake.priority == "low"


def test_changing_the_plant_triggers_a_new_analysis_at_once():
    plants = {"d1": get_profile("pothos")}
    service = build_service(Settings(offline=True), None, profile_for=lambda d: plants[d])
    assert service.handle_reading(reading(0, moisture=25.0, device_id="d1")).priority == "high"
    assert service.handle_reading(reading(1, moisture=25.0, device_id="d1")) is None  # nothing new

    plants["d1"] = get_profile("snake_plant")
    result = service.handle_reading(reading(2, moisture=25.0, device_id="d1"))
    assert result.trigger == "plant profile changed" and result.priority == "low"
