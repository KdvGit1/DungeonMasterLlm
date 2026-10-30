from dndm.launcher import MODELS, Runtime, gpu_from_ollama_log

AMD = ('time=x level=INFO msg="inference compute" id=0 library=ROCm compute=gfx1100 name=ROCm0 '
       'description="AMD Radeon RX 7800 XT" type=discrete total="16.0 GiB" available="15.2 GiB"\n')
CPU = 'time=x level=INFO msg="inference compute" id=cpu library=cpu compute="" total="15.9 GiB" available="9 GiB"\n'


def test_gpu_memory_from_ollama_log(tmp_path):
    log = tmp_path / "ollama.log"
    log.write_text("starting\n" + CPU + AMD, encoding="utf-8")
    assert gpu_from_ollama_log(log) == 16.0
    log.write_text(CPU, encoding="utf-8")
    assert gpu_from_ollama_log(log) is None
    assert gpu_from_ollama_log(tmp_path / "missing.log") is None


def test_model_choice_by_gpu(tmp_path, monkeypatch):
    monkeypatch.setenv("DNDM_INSTALL_ROOT", str(tmp_path))
    monkeypatch.setenv("DNDM_HOME", str(tmp_path / "userdata"))
    rt = Runtime()
    for vram, key in ((12.0, "recommended"), (8.0, "light"), (None, "light")):
        monkeypatch.setattr(Runtime, "vram_gb", lambda self, wait=0, v=vram: v)
        monkeypatch.setattr(Runtime, "saved_model", lambda self: None)
        assert rt.pick_model() == MODELS[key]["name"]
