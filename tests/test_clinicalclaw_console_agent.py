from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from clinagent.console.agent import SKILLS_DIR, build_console_agent, build_routed_task, route_with_llm
from clinagent.console.semantic_router import retrieve_semantic_workflow_candidates
from clinagent.engine.providers.llm import LLMMessage, LLMProvider, LLMResponse


class FakeRouterLLM(LLMProvider):
    name = "fake-router"

    async def chat(self, messages: list[LLMMessage], on_chunk=None, cancel_event=None, tools=None):
        return LLMResponse(
            content=(
                '{"workflow_id":"radiation_safety_monitor","confidence":0.93,'
                '"reason":"The request asks about a radiation incident alert.",'
                '"next_action":"Open safety and inspect the local case library."}'
            ),
            model="fake-router-model",
            tokens_used=42,
        )


class LowConfidenceRouterLLM(LLMProvider):
    name = "low-confidence-router"

    async def chat(self, messages: list[LLMMessage], on_chunk=None, cancel_event=None, tools=None):
        return LLMResponse(
            content=(
                '{"workflow_id":"neuro_longitudinal","confidence":0.42,'
                '"reason":"This might be a neuro longitudinal request, but the intent is not fully explicit.",'
                '"next_action":"Suggest the neuro module but stay in general chat.",'
                '"alternatives":["general_chat","radiation_safety_monitor"]}'
            ),
            model="fake-router-model",
            tokens_used=38,
        )


class BrokenRouterLLM(LLMProvider):
    name = "broken-router"

    async def chat(self, messages: list[LLMMessage], on_chunk=None, cancel_event=None, tools=None):
        raise RuntimeError("router unavailable")


class GeneralChatRouterLLM(LLMProvider):
    name = "general-chat-router"

    async def chat(self, messages: list[LLMMessage], on_chunk=None, cancel_event=None, tools=None):
        return LLMResponse(
            content=(
                '{"workflow_id":"general_chat","confidence":0.55,'
                '"reason":"This looks conversational.",'
                '"next_action":"Respond in chat."}'
            ),
            model="fake-router-model",
            tokens_used=24,
        )


def _build_client():
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def test_route_with_llm_uses_structured_json():
    payload = __import__("asyncio").run(
        route_with_llm(FakeRouterLLM(), "Check whether this radiation incident should trigger an alert.")
    )

    assert payload["workflow_id"] == "radiation_safety_monitor"
    assert payload["target_module"] == "safety"
    assert payload["fallback"] is False


def test_route_with_llm_stays_home_when_confidence_is_low():
    payload = __import__("asyncio").run(
        route_with_llm(LowConfidenceRouterLLM(), "Review this clinical case for me.")
    )

    assert payload["workflow_id"] == "general_chat"
    assert payload["target_module"] == "home"
    assert payload["suggested_module"] is None


def test_route_with_llm_falls_back_to_queue_when_llm_fails():
    payload = __import__("asyncio").run(
        route_with_llm(BrokenRouterLLM(), "Should this referral move into the urgent queue today?")
    )

    assert payload["workflow_id"] == "queue_triage"
    assert payload["target_module"] == "queue"
    assert payload["fallback"] is True


def test_route_with_llm_falls_back_to_diagnosis_when_llm_fails():
    payload = __import__("asyncio").run(
        route_with_llm(BrokenRouterLLM(), "Does this report suggest a missed vertebral fracture workup gap?")
    )

    assert payload["workflow_id"] == "missed_diagnosis_detection"
    assert payload["target_module"] == "diagnosis"
    assert payload["fallback"] is True


def test_route_with_llm_falls_back_to_screening_when_llm_fails():
    payload = __import__("asyncio").run(
        route_with_llm(BrokenRouterLLM(), "Does this positive FIT still need colonoscopy follow-up?")
    )

    assert payload["workflow_id"] == "screening_gap_closure"
    assert payload["target_module"] == "screening"
    assert payload["fallback"] is True


def test_route_with_llm_falls_back_to_radonc_when_llm_fails():
    payload = __import__("asyncio").run(
        route_with_llm(BrokenRouterLLM(), "Optimize this lung SBRT plan and lower heart dose.")
    )

    assert payload["workflow_id"] == "radonc_plan_optimization"
    assert payload["target_module"] == "radonc_plan"
    assert payload["fallback"] is True


def test_semantic_router_retrieves_queue_from_referral_backlog_language():
    candidates = retrieve_semantic_workflow_candidates(
        "Reprioritize the referral backlog and decide what should be seen sooner.",
        top_k=3,
    )

    assert candidates
    assert candidates[0]["workflow_id"] == "queue_triage"


def test_route_with_llm_continues_active_workflow_on_follow_up_message():
    session_memory = {
        "payload": {
            "active_workflow_id": "neuro_report",
            "active_intent_label": "Neuro MRI review",
            "conversation_mode": "workflow",
            "last_confidence": 0.88,
            "recent_user_messages": ["Review this brain MRI follow-up."],
            "recent_routes": [{"workflow_id": "neuro_report", "intent_label": "Neuro MRI review", "confidence": 0.88}],
        }
    }

    with patch("clinagent.console.intent_session.get_session_memory", return_value=session_memory):
        payload = __import__("asyncio").run(
            route_with_llm(
                GeneralChatRouterLLM(),
                "and compare it with the last scan",
                session_id="session-123",
            )
        )

    assert payload["workflow_id"] == "neuro_report"
    assert payload["target_module"] == "neuro_report"
    assert payload["fallback"] is False


def test_build_routed_task_mentions_selected_workflow():
    task = build_routed_task(
        {"workflow_id": "neuro_longitudinal"},
        "Review the longitudinal MRI trend.",
    )

    assert "Workflow: neuro_longitudinal" in task
    assert "clinical_report_presentation" in task
    assert "clinical_report_generator" in task
    assert "neuro_report_generator" in task
    assert "neuro_report_presenter" in task
    assert "Review the longitudinal MRI trend." in task


def test_build_routed_task_mentions_neuro_knowledge_tools_for_neuro_report():
    task = build_routed_task(
        {"workflow_id": "neuro_report"},
        "Find the right MR-RATE case before opening the MRI report workspace.",
    )

    assert "neuro knowledge search" in task
    assert "Find the right MR-RATE case" in task


def test_build_routed_task_keeps_general_chat_direct():
    task = build_routed_task(
        {"workflow_id": "general_chat"},
        "hi",
    )

    assert "clinical_report_presentation" not in task
    assert "reply in one short sentence" in task


def test_build_console_agent_loads_presentation_skill():
    fake_agent = MagicMock()

    with patch("clinagent.console.agent.create_agent", return_value=fake_agent) as create_agent:
        build_console_agent(MagicMock())

    assert SKILLS_DIR in create_agent.call_args.kwargs["skills"]
    allowed = fake_agent.allow_only_tools.call_args.args
    assert "use_skill" in allowed
    assert "list_skills" in allowed
    assert "get_findings_workspace" in allowed
    assert "get_queue_workspace" in allowed
    assert "get_diagnosis_workspace" in allowed
    assert "get_screening_workspace" in allowed
    assert "lesion_trend_plotter" in allowed
    assert "treatment_event_timeline_renderer" in allowed
    assert "key_slice_selector" in allowed
    assert "overlay_composer" in allowed
    assert "risk_signal_renderer" in allowed
    assert "render_clinical_report" in allowed
    assert "build_neuro_visualization_bundle" in allowed
    assert "search_neuro_knowledge" in allowed
    assert "get_neuro_knowledge_case" in allowed
    assert "get_neuro_knowledge_case_assets" in allowed
    assert "get_neuro_knowledge_study" in allowed
    assert "get_neuro_knowledge_cohort" in allowed


def test_build_console_agent_uses_workflow_profile_restrictions():
    fake_agent = MagicMock()

    with patch("clinagent.console.agent.create_agent", return_value=fake_agent):
        build_console_agent(MagicMock(), workflow_id="queue_triage")

    allowed = fake_agent.allow_only_tools.call_args.args
    assert "get_queue_workspace" in allowed
    assert "get_findings_workspace" not in allowed
    assert "get_neuro_longitudinal_workspace" not in allowed


def test_build_console_agent_allows_neuro_knowledge_tools_for_neuro_report():
    fake_agent = MagicMock()

    with patch("clinagent.console.agent.create_agent", return_value=fake_agent):
        build_console_agent(MagicMock(), workflow_id="neuro_report")

    allowed = fake_agent.allow_only_tools.call_args.args
    assert "search_neuro_knowledge" in allowed
    assert "get_neuro_knowledge_case" in allowed
    assert "get_neuro_knowledge_case_assets" in allowed
    assert "get_neuro_knowledge_study" in allowed
    assert "get_neuro_knowledge_cohort" in allowed
    assert "get_findings_workspace" not in allowed


def test_demo_execute_stream_emits_routed_and_done():
    class FakeAgent:
        async def invoke(self, task, on_event=None):
            if on_event:
                on_event("tool_call", {"name": "get_safety_case"})
                on_event("tool_result", {"name": "get_safety_case", "success": True, "preview": "ok"})
            return MagicMock(status="done", result="Mock streamed answer", iterations=2)

    async def fake_route_with_llm(llm, message):
        return {
            "workflow_id": "radiation_safety_monitor",
            "workflow": {
                "id": "radiation_safety_monitor",
                "title": "Radiation Safety Monitor",
                "module": "safety",
                "tools": ["get_safety_case"],
            },
            "target_module": "safety",
            "suggested_module": "safety",
            "confidence": 0.91,
            "reason": "Detected a radiation safety incident request.",
            "next_action": "Open safety workspace.",
            "alternatives": [{"module": "home", "title": "General Clinical Command"}],
            "fallback": False,
        }

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.build_console_agent", return_value=FakeAgent()), \
         patch("clinagent.gateway.server.route_with_llm", side_effect=fake_route_with_llm):
        client = _build_client()
        response = client.post("/api/demo/execute-stream", json={"message": "Alert the QA lead about this radiation issue."})

    assert response.status_code == 200
    assert "event: routed" in response.text
    assert "event: done" in response.text
    assert "Mock streamed answer" in response.text


def test_demo_execute_stream_short_circuits_smalltalk():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()
        response = client.post("/api/demo/execute-stream", json={"message": "hi"})

    assert response.status_code == 200
    assert "Hi. How can I help?" in response.text
    assert "Neuro Longitudinal Review" not in response.text


def test_dev_execute_stream_includes_profile_and_explanation():
    class FakeAgent:
        async def invoke(self, task, on_event=None):
            if on_event:
                on_event("tool_call", {"name": "get_queue_workspace"})
                on_event("tool_result", {"name": "get_queue_workspace", "success": True, "preview": "queued"})
            return MagicMock(status="done", result="Developer trace ready", iterations=1)

    async def fake_route_with_llm(llm, message):
        return {
            "workflow_id": "queue_triage",
            "workflow": {
                "id": "queue_triage",
                "title": "Queue Triage",
                "module": "queue",
                "tools": ["get_queue_workspace"],
            },
            "target_module": "queue",
            "suggested_module": "queue",
            "confidence": 0.88,
            "reason": "Detected queue triage intent.",
            "next_action": "Open queue workspace.",
            "alternatives": [],
            "fallback": False,
        }

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.build_console_agent", return_value=FakeAgent()), \
         patch("clinagent.gateway.server.route_with_llm", side_effect=fake_route_with_llm):
        client = _build_client()
        response = client.post("/api/dev/execute-stream", json={"message": "Prioritize this follow-up queue."})

    assert response.status_code == 200
    assert '"profile"' in response.text
    assert '"developer_explanation"' in response.text
    assert '"handoff"' in response.text
    assert "Developer trace ready" in response.text


def test_demo_execute_stream_includes_neuro_report_artifact():
    class FakeAgent:
        async def invoke(self, task, on_event=None):
            if on_event:
                on_event("tool_call", {"name": "get_neuro_longitudinal_report"})
            return MagicMock(status="done", result="### MRI Trend Analysis\nStable interval response.", iterations=3)

    async def fake_route_with_llm(llm, message):
        return {
            "workflow_id": "neuro_longitudinal",
            "workflow": {
                "id": "neuro_longitudinal",
                "title": "Neuro Longitudinal Review",
                "module": "neuro",
                "tools": ["get_neuro_longitudinal_report"],
            },
            "target_module": "neuro",
            "suggested_module": "neuro",
            "confidence": 0.89,
            "reason": "Detected a longitudinal neuro-oncology review request.",
            "next_action": "Open neuro workspace.",
            "alternatives": [],
            "fallback": False,
        }

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.build_console_agent", return_value=FakeAgent()), \
         patch("clinagent.gateway.server.route_with_llm", side_effect=fake_route_with_llm):
        client = _build_client()
        response = client.post(
            "/api/demo/execute-stream",
            json={"message": "Review this longitudinal brain MRI follow-up and draft a physician report."},
        )

    assert response.status_code == 200
    assert '"artifact": {' in response.text
    assert '"kind": "neuro_report"' in response.text
    assert '"module": "neuro"' in response.text


def test_demo_execute_stream_neuro_report_includes_analysis_plan():
    class FakeDemoStore:
        def get_examples(self):
            return [
                {
                    "case_id": "1278:EXAMPLE",
                    "patient_id": "1278",
                    "study_id": "EXAMPLE",
                    "title": "Patient 1278 · Example",
                    "description": "Curated MRI example",
                    "thumbnail_base64": "abc",
                    "age": 71,
                    "sex": "F",
                    "default_mode": "full_agent",
                    "supported_modes": ["vanilla", "seg_overlay", "tool_output", "full_agent"],
                    "analysis_plan": {
                        "requested_goal": "Launch a curated example",
                        "recommended_workflow": "neuro_report",
                        "recommended_mode": "full_agent",
                        "can_execute": True,
                        "autorun": True,
                        "allowed_analyses": ["structured_report_generation"],
                        "blocked_analyses": [],
                        "missing_inputs": [],
                        "rationale": ["Curated example is runnable."],
                        "safe_fallback_mode": "vanilla",
                        "stages": ["intake"],
                        "handoff_summary": "I found a curated MRI case with enough data to start the recommended analysis automatically.",
                    },
                    "capability_profile": {
                        "has_demographics": True,
                        "has_single_study_mri": True,
                        "imaging_format": "nifti",
                        "has_segmentation": True,
                        "has_longitudinal_priors": True,
                        "has_report_context": True,
                        "has_ehr_context": True,
                        "available_inputs": ["nifti_mri", "segmentation", "demographics"],
                        "missing_inputs": [],
                        "blocked_reasons": [],
                    },
                }
            ]

        def get_patients(self):
            return {"patients": [{"study_count": 16}]}

    async def fake_route_with_llm(llm, message):
        return {
            "workflow_id": "neuro_report",
            "workflow": {
                "id": "neuro_report",
                "title": "Neuro MRI Report Generator",
                "module": "neuro_report",
                "tools": [],
            },
            "target_module": "neuro_report",
            "suggested_module": "neuro_report",
            "confidence": 0.94,
            "reason": "Detected a neuro MRI reporting request.",
            "next_action": "Open the neuro workspace.",
            "alternatives": [],
            "fallback": False,
        }

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.route_with_llm", side_effect=fake_route_with_llm), \
         patch("clinagent.gateway.server._get_neuro_report_demo_components", return_value=(["vanilla", "seg_overlay", "tool_output", "full_agent"], FakeDemoStore())):
        client = _build_client()
        response = client.post(
            "/api/demo/execute-stream",
            json={"message": "Open the Neuro MRI Report Generator and show me a curated brain MRI case."},
        )

    assert response.status_code == 200
    assert '"analysis_plan": {' in response.text
    assert '"capability_profile": {' in response.text
    assert '"analysisPlanSummary": {' in response.text
    assert '"planningResult": {' in response.text
    assert '"executionReadiness": "ready"' in response.text
    assert '"viewer_type": "nifti"' in response.text
    assert '"/demo/analysis/neuro-report?' in response.text
    assert 'autorun=1' not in response.text


def test_demo_execute_stream_neuro_report_dicom_handoff_uses_dicomweb_viewer():
    class FakeDemoStore:
        def get_examples(self):
            return [
                {
                    "case_id": "1278:EXAMPLE",
                    "patient_id": "1278",
                    "study_id": "EXAMPLE",
                    "title": "Patient 1278 · Example",
                    "description": "Curated MRI example",
                    "thumbnail_base64": "abc",
                    "age": 71,
                    "sex": "F",
                    "default_mode": "full_agent",
                    "supported_modes": ["vanilla", "seg_overlay", "tool_output", "full_agent"],
                    "analysis_plan": {
                        "requested_goal": "Launch a curated example",
                        "recommended_workflow": "neuro_report",
                        "recommended_mode": "full_agent",
                        "can_execute": True,
                        "autorun": True,
                        "allowed_analyses": ["structured_report_generation"],
                        "blocked_analyses": [],
                        "missing_inputs": [],
                        "rationale": ["Curated example is runnable."],
                        "safe_fallback_mode": "vanilla",
                        "stages": ["intake"],
                        "handoff_summary": "I found a curated MRI case with enough data to start the recommended analysis automatically.",
                    },
                    "capability_profile": {
                        "has_demographics": True,
                        "has_single_study_mri": True,
                        "imaging_format": "nifti",
                        "has_segmentation": True,
                        "has_longitudinal_priors": True,
                        "has_report_context": True,
                        "has_ehr_context": True,
                        "available_inputs": ["nifti_mri", "segmentation", "demographics"],
                        "missing_inputs": [],
                        "blocked_reasons": [],
                    },
                }
            ]

        def get_patients(self):
            return {"patients": [{"study_count": 16}]}

    async def fake_route_with_llm(llm, message):
        return {
            "workflow_id": "neuro_report",
            "workflow": {
                "id": "neuro_report",
                "title": "Neuro MRI Report Generator",
                "module": "neuro_report",
                "tools": [],
            },
            "target_module": "neuro_report",
            "suggested_module": "neuro_report",
            "confidence": 0.94,
            "reason": "Detected a neuro MRI reporting request.",
            "next_action": "Open the neuro workspace.",
            "alternatives": [],
            "fallback": False,
        }

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.load_settings", return_value=MagicMock(dicomweb_base_url="https://dicom.example", ohif_base_url="https://ohif.example")), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.route_with_llm", side_effect=fake_route_with_llm), \
         patch("clinagent.gateway.server._get_neuro_report_demo_components", return_value=(["vanilla", "seg_overlay", "tool_output", "full_agent"], FakeDemoStore())):
        client = _build_client()
        response = client.post(
            "/api/demo/execute-stream",
            json={"message": "I only have a PACS DICOM brain MRI study. What can you do next?"},
        )

    assert response.status_code == 200
    assert '"viewer_type": "dicomweb"' in response.text


def test_demo_execute_stream_radonc_plan_includes_analysis_plan():
    class FakeRouteLLM:
        pass

    async def fake_route_with_llm(llm, message):
        return {
            "workflow_id": "radonc_plan_optimization",
            "workflow": {
                "id": "radonc_plan_optimization",
                "title": "RadOnc Plan Optimization",
                "module": "radonc_plan",
                "tools": [],
            },
            "target_module": "radonc_plan",
            "suggested_module": "radonc_plan",
            "confidence": 0.95,
            "reason": "Detected radiation treatment planning optimization intent.",
            "next_action": "Open the radonc planning workspace.",
            "alternatives": [],
            "fallback": False,
        }

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=FakeRouteLLM()), \
         patch("clinagent.gateway.server.route_with_llm", side_effect=fake_route_with_llm):
        client = _build_client()
        response = client.post(
            "/api/demo/execute-stream",
            json={"message": "Optimize this lung SBRT plan and summarize the DVH trade-offs."},
        )

    assert response.status_code == 200
    assert '"workflow_id": "radonc_plan_optimization"' in response.text
    assert '"kind": "radonc_plan"' in response.text
    assert '"analysis_plan": {' in response.text
    assert '"capability_profile": {' in response.text
    assert '"planning_result": {' in response.text
    assert '"/demo/analysis/radonc-plan?' in response.text
    assert '"executionReadiness": "' in response.text
    assert '"context_sources": ["radonc_context", "mock_tps_connector"]' in response.text


def test_build_routed_task_mentions_findings_presentation_skill():
    task = build_routed_task(
        {"workflow_id": "findings_closure"},
        "Does this critical lab need escalation?",
    )

    assert "Workflow: findings_closure" in task
    assert "clinical_report_presentation" in task
    assert "findings_brief_presenter" in task


def test_build_routed_task_mentions_queue_presentation_skill():
    task = build_routed_task(
        {"workflow_id": "queue_triage"},
        "Should this referral move into the urgent queue?",
    )

    assert "Workflow: queue_triage" in task
    assert "clinical_report_presentation" in task
    assert "queue_triage_presenter" in task


def test_build_routed_task_mentions_missed_diagnosis_presentation_skill():
    task = build_routed_task(
        {"workflow_id": "missed_diagnosis_detection"},
        "Does this report suggest a missed vertebral fracture workup gap?",
    )

    assert "Workflow: missed_diagnosis_detection" in task
    assert "clinical_report_presentation" in task
    assert "missed_diagnosis_presenter" in task


def test_build_routed_task_mentions_screening_gap_presentation_skill():
    task = build_routed_task(
        {"workflow_id": "screening_gap_closure"},
        "Does this positive FIT still need colonoscopy follow-up?",
    )

    assert "Workflow: screening_gap_closure" in task
    assert "clinical_report_presentation" in task
    assert "screening_gap_presenter" in task
