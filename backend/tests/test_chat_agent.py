import json
from datetime import timedelta

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from greenpulse_ai import Settings, build_pipeline
from greenpulse_ai.agents.chat import ChatAgent, ChatTurn
from greenpulse_ai.device_state import DeviceStore
from greenpulse_ai.plant_profiles import get_profile
from greenpulse_ai.watering import WateringDecision

from conftest import T0, reading

ALL_TOOLS = ["current_status", "plant_doctor_report", "sensor_history", "watering_log"]


class ScriptedChatModel:
    """Stands in for a tool-calling chat model: bind_tools() records the tool names, and each invoke()
    returns the next scripted reply (or raises it) and records the messages it was given."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list] = []
        self.tools: list[str] = []

    def bind_tools(self, tools, **_):
        self.tools = [tool.name for tool in tools]
        return self

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def tool_call(name, args=None, call_id="call-1"):
    return AIMessage("", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def make_store(with_data=True):
    """A device read every 10 minutes from 08:00 to 09:00 UTC (13:30-14:30 in Colombo), watered by hand at 08:20."""
    store = DeviceStore(get_profile("pothos"), lambda device_id: False, lambda: T0)
    if with_data:
        for i, moisture in enumerate((44.0, 43.0, 60.0, 58.5, 57.0, 55.5, 54.0)):
            store.record_reading(reading(-60 + 10 * i, moisture=moisture, device_id="d1"))
        store.record_pump_state("d1", {"state": "on", "source": "manual", "duration_s": 5}, T0 - timedelta(minutes=40))
        result = build_pipeline(Settings(offline=True), None).run(reading(moisture=54.0, device_id="d1"))
        result = result.model_copy(update={"generated_at": T0})
        store.record_result(result, WateringDecision(False, "Soil moisture is optimal", False))
    return store


def make_agent(replies=None, with_data=True):
    llm = ScriptedChatModel(replies) if replies is not None else None
    agent = ChatAgent(make_store(with_data), llm, "groq:test-model", "Colombo, LK", "Asia/Colombo")
    return agent, llm


def test_agent_looks_the_status_up_then_answers():
    agent, llm = make_agent([tool_call("current_status"), AIMessage("Your pothos is doing well: soil is at 54 %.")])
    answer = agent.ask("d1", "How is my plant doing?")

    assert answer.source == "llm" and answer.model == "groq:test-model"
    assert answer.answer == "Your pothos is doing well: soil is at 54 %."
    assert answer.tools == ["current_status"]
    assert llm.tools == ALL_TOOLS

    system = llm.calls[0][0]
    assert isinstance(system, SystemMessage)
    assert "Pothos (Money Plant)" in system.content and "Colombo, LK" in system.content
    assert "14:30" in system.content  # 09:00 UTC is 14:30 in Sri Lanka
    assert "soil moisture 35-65 %" in system.content and "soggy soil causes root rot" in system.content

    tool_result = llm.calls[1][-1]
    assert isinstance(tool_result, ToolMessage) and tool_result.tool_call_id == "call-1"
    status = json.loads(tool_result.content)
    assert status["device_online"] is True
    assert status["last_reading"] == "14:30 (just now)"
    assert status["readings"]["soil_moisture"] == {"value": 54.0, "unit": "%", "ideal_range": "35-65", "state": "optimal"}


def test_earlier_messages_are_sent_for_follow_up_questions():
    agent, llm = make_agent([AIMessage("About 40 minutes ago.")])
    history = [ChatTurn(role="user", content="How is my plant?"), ChatTurn(role="assistant", content="It is fine.")]
    agent.ask("d1", "And when was it watered?", history)

    messages = llm.calls[0]
    assert [type(m) for m in messages] == [SystemMessage, HumanMessage, AIMessage, HumanMessage]
    assert messages[-1].content == "And when was it watered?"


def test_plant_doctor_report_tool():
    agent, _ = make_agent()
    report = agent.plant_doctor_report("d1")
    assert report["priority"] == "low"
    assert report["analysed"] == "14:30 (just now)"
    assert report["auto_watering_decision"]["reason"] == "Soil moisture is optimal"
    assert "summary" in report["weather"]


def test_sensor_history_tool():
    agent, _ = make_agent()
    history = agent.sensor_history("d1", 2)
    assert history["readings"] == 7
    assert history["from"] == "13:30 (1.0 h ago)"
    soil = history["soil_moisture"]
    assert soil["lowest"] == 43.0 and soil["lowest_at"] == "13:40 (50 min ago)"
    assert soil["highest"] == 60.0 and soil["first"] == 44.0 and soil["last"] == 54.0
    assert history["waterings"] == 1
    # 2 h in 30-min buckets from 12:30; the first readings fall in the one centred on 13:45
    assert history["soil_moisture_over_time"] == [{"time": "13:45", "value": 49.0}, {"time": "14:15", "value": 56.2}]


def test_hours_are_clamped_to_the_stored_day():
    agent, _ = make_agent()
    assert agent.sensor_history("d1", 500)["period"] == "last 24 h"


def test_watering_log_tool():
    agent, _ = make_agent()
    log = agent.watering_log("d1")
    assert log["auto_watering"] == "off"
    assert log["last_watered"] == "13:50 (40 min ago)"
    assert log["events_newest_first"] == [{"time": "13:50 (40 min ago)", "event": "pump started for 5 s (manual)"}]


def test_unknown_tools_and_bad_arguments_are_reported_back_to_the_model():
    agent, llm = make_agent(
        [
            tool_call("water_the_plant", call_id="a"),
            tool_call("sensor_history", {"hours": "lots"}, call_id="b"),
            AIMessage("I can't water the plant myself; use the Water now button."),
        ]
    )
    answer = agent.ask("d1", "Water my plant")
    assert answer.source == "llm"
    assert answer.tools == ["water_the_plant", "sensor_history"]
    assert "no tool called" in json.loads(llm.calls[1][-1].content)["error"]
    assert "error" in json.loads(llm.calls[2][-1].content)


def test_llm_failure_falls_back_to_the_rule_based_answer():
    agent, _ = make_agent([RuntimeError("Groq timed out")])
    answer = agent.ask("d1", "How is my plant doing?")
    assert answer.source == "rules-fallback" and answer.model is None
    assert answer.answer.startswith("No action needed.")
    assert "soil moisture 54% (ideal)" in answer.answer


def test_a_model_that_never_stops_calling_tools_falls_back():
    agent, _ = make_agent([tool_call("current_status")] * 4)
    answer = agent.ask("d1", "How is my plant doing?")
    assert answer.source == "rules-fallback"
    assert answer.tools == ["current_status"] * 4


def test_offline_answer_adds_watering_details_when_asked():
    agent, _ = make_agent()
    answer = agent.ask("d1", "When did it last get water?")
    assert answer.source == "rules" and answer.tools == []
    assert "temperature 26 °C (ideal)" in answer.answer
    assert "Last watering: 13:50 (40 min ago)." in answer.answer
    assert "Auto-watering is off." in answer.answer


def test_no_data_yet():
    agent, _ = make_agent(with_data=False)
    assert "no readings from d1 yet" in agent.ask("d1", "How is my plant?").answer
    assert "error" in agent.current_status("d1")
    assert "error" in agent.plant_doctor_report("d1")
    assert "error" in agent.sensor_history("d1")
