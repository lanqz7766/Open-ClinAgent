from __future__ import annotations

import importlib


def _service_module():
    from clinagent.gateway import brain_tumor_service

    return importlib.reload(brain_tumor_service)


def _reset_readiness(module, monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "_readiness",
        {
            "status": "starting",
            "service_ready": False,
            "model_loaded": False,
            "warmup_level": "pending",
            "warmup_started_at": None,
            "warmup_completed_at": None,
            "warmup_duration_s": None,
            "warmup_error": None,
        },
    )
    monkeypatch.setattr(module, "_nnunet_fast_predictors", {})
    monkeypatch.setattr(module, "_fast_predictors", {})


def test_fast_nnunet_warmup_marks_model_loaded(monkeypatch) -> None:
    module = _service_module()
    _reset_readiness(module, monkeypatch)
    monkeypatch.setattr(module, "WARMUP_ON_START", True)
    monkeypatch.setattr(module, "WARMUP_MODALITIES_JSON", "")
    monkeypatch.setattr(module, "ENGINE", "nnunetv2")
    monkeypatch.setattr(module, "NNUNET_RUNTIME", "fast")

    def load_predictor(mode: str):
        module._nnunet_fast_predictors[(mode, "checkpoint", "0")] = object()
        return object()

    monkeypatch.setattr(module, "_get_nnunet_fast_predictor", load_predictor)
    module._warmup_model()

    health = module._health_payload()
    assert health["ok"] is True
    assert health["service_ready"] is True
    assert health["model_loaded"] is True
    assert health["warmup_level"] == "model_loaded"
    assert health["nnunet_fast_predictors_loaded"] == 1


def test_cli_runtime_is_ready_but_does_not_claim_persistent_model(monkeypatch) -> None:
    module = _service_module()
    _reset_readiness(module, monkeypatch)
    monkeypatch.setattr(module, "WARMUP_ON_START", True)
    monkeypatch.setattr(module, "WARMUP_MODALITIES_JSON", "")
    monkeypatch.setattr(module, "ENGINE", "nnunetv2")
    monkeypatch.setattr(module, "NNUNET_RUNTIME", "cli")
    module._warmup_model()

    health = module._health_payload()
    assert health["service_ready"] is True
    assert health["model_loaded"] is False
    assert health["warmup_level"] == "runtime_checked"


def test_warmup_failure_keeps_service_unready_and_hides_internal_error(monkeypatch) -> None:
    module = _service_module()
    _reset_readiness(module, monkeypatch)
    monkeypatch.setattr(module, "WARMUP_ON_START", True)
    monkeypatch.setattr(module, "WARMUP_MODALITIES_JSON", "")
    monkeypatch.setattr(module, "ENGINE", "nnunetv2")
    monkeypatch.setattr(module, "NNUNET_RUNTIME", "fast")

    def fail_predictor(_mode: str):
        raise RuntimeError("private checkpoint path should stay in logs")

    monkeypatch.setattr(module, "_get_nnunet_fast_predictor", fail_predictor)
    module._warmup_model()

    health = module._health_payload()
    assert health["ok"] is False
    assert health["service_ready"] is False
    assert health["status"] == "failed"
    assert health["warmup_error"] == "Model warmup failed; review service logs."
    assert "checkpoint" not in health["warmup_error"]
