from clinagent.console.workspace import console_snapshot, dev_console_snapshot, route_general_query


def test_console_snapshot_includes_multiple_modules():
    payload = console_snapshot()

    assert payload["title"] == "ClinAgent Console"
    assert len(payload["workflows"]) >= 7
    assert payload["modules"]["report_quality"]["title"]
    assert payload["modules"]["findings"]["title"]
    assert payload["modules"]["queue"]["title"]
    assert payload["modules"]["diagnosis"]["title"]
    assert payload["modules"]["screening"]["title"]
    assert payload["modules"]["neuro"]["title"]
    assert payload["modules"]["safety"]["title"]
    assert any(item["family_id"] == "neuro" for item in payload["workflow_families"])
    assert any(item["family_id"] == "radonc" for item in payload["workflow_families"])
    assert any(item["workflow_id"] == "neuro.structural_report" for item in payload["workflow_registry"])
    assert any(item["workflow_id"] == "radonc.dose_prediction" for item in payload["workflow_registry"])
    assert "profiles" not in payload


def test_dev_console_snapshot_adds_profiles_and_actions():
    payload = dev_console_snapshot()

    assert payload["surface"] == "developer"
    assert payload["profiles"]
    assert payload["profiles"][0]["workflow_id"]
    assert payload["developer_actions"]
    assert payload["subagent_roles"]
    assert "lane_status" in payload
    assert payload["recent_trace_summary"]["status"] == "idle"


def test_route_general_query_can_select_report_quality_findings_queue_diagnosis_screening_neuro_or_safety():
    report_quality = route_general_query("Check this report draft for identifiers, terminology, and compliance problems.")
    findings = route_general_query("Does this critical potassium result need urgent escalation?")
    queue = route_general_query("Should this high-risk referral be expedited in the queue today?")
    diagnosis = route_general_query("Does this report suggest a missed vertebral fracture workup gap?")
    screening = route_general_query("Does this positive FIT still need colonoscopy follow-up?")
    neuro = route_general_query("Review this MRI longitudinal atrophy trend and generate a report.")
    metastasis = route_general_query("Review this longitudinal brain metastasis MRI trend and draft a physician report.")
    safety = route_general_query("Check whether this radiation plan incident should trigger an alert.")

    assert report_quality["target_module"] == "report_quality"
    assert "deidentification_checker" in report_quality["suggested_steps"]
    assert findings["target_module"] == "findings"
    assert "closure_checker" in findings["suggested_steps"]
    assert queue["target_module"] == "queue"
    assert "priority_scorer" in queue["suggested_steps"]
    assert diagnosis["target_module"] == "diagnosis"
    assert "workup_recommender" in diagnosis["suggested_steps"]
    assert screening["target_module"] == "screening"
    assert "gap_checker" in screening["suggested_steps"]
    assert neuro["target_module"] == "neuro_report"
    assert "slice_selector" in neuro["suggested_steps"]
    assert metastasis["target_module"] == "neuro_report"
    assert metastasis["workflow"]["id"] == "neuro_report"
    assert metastasis["workflow_family"] == "neuro"
    assert metastasis["workflow_task_id"] == "neuro.response_review"
    assert safety["target_module"] == "safety"
    assert "risk_tier_engine" in safety["suggested_steps"]


def test_route_general_query_can_select_radonc_plan_optimization():
    radonc = route_general_query("Optimize this lung SBRT plan and lower heart dose while keeping coverage strong.")

    assert radonc["target_module"] == "radonc_plan"
    assert radonc["target_view"] == "radonc-plan"
    assert radonc["workflow"]["id"] == "radonc_plan_optimization"
    assert radonc["workflow_family"] == "radonc"
    assert radonc["primary_goal"] == "plan_optimization"
    assert radonc["dashboard_profile"] == "plan_optimization"
    assert radonc["workflow_task_id"] == "radonc.plan_optimization"
    assert "dvh_constraint_analyzer" in radonc["suggested_steps"]
