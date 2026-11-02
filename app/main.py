from __future__ import annotations
import asyncio, json, os, platform, threading, time
from queue import Queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Local LLM Bench", version="1.0.0",
              description="Benchmark local Ollama models.")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
benchmark_lock = threading.Lock()

class BenchRequest(BaseModel):
    model: str
    prompt: str = Field(min_length=1, max_length=12000)
    runs: int = Field(default=1, ge=1, le=5)
    temperature: float = Field(default=0.2, ge=0, le=2)
    num_predict: int = Field(default=256, ge=16, le=2048)

def gpu_snapshot() -> dict[str, Any]:
    """Best-effort NVIDIA metrics; gracefully returns unavailable on other systems."""
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        result = {"available": True, "name": pynvml.nvmlDeviceGetName(h),
                  "utilization_percent": util.gpu,
                  "memory_used_mb": round(mem.used / 1024**2, 1),
                  "memory_total_mb": round(mem.total / 1024**2, 1)}
        pynvml.nvmlShutdown()
        return result
    except Exception:
        return {"available": False}

def hardware_snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_used_mb": round((vm.total - vm.available) / 1024**2, 1),
        "ram_total_mb": round(vm.total / 1024**2, 1),
        "ram_percent": vm.percent,
        "gpu": gpu_snapshot()
    }

def response_chunk(item: dict[str, Any]) -> str:
    response = item.get("response")
    if isinstance(response, str) and response:
        return response
    message = item.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def run_once(
    model: str,
    prompt: str,
    temperature: float,
    num_predict: int,
    on_chunk: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    stop = threading.Event()
    def sampler():
        while not stop.is_set():
            samples.append({"elapsed_s": round(time.perf_counter() - started, 2),
                            **hardware_snapshot()})
            stop.wait(0.5)
    payload = {"model": model, "prompt": prompt, "stream": True,
               "options": {"temperature": temperature, "num_predict": num_predict}}
    started = time.perf_counter()
    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()
    first_token_s = None
    output = ""
    thinking = ""
    final: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            with client.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")
                    raise RuntimeError(f"Ollama HTTP {response.status_code}: {detail}")
                for line in response.iter_lines():
                    if not line:
                        continue
                    item = json.loads(line)
                    chunk = response_chunk(item)
                    thinking_chunk = item.get("thinking", "")
                    if chunk and first_token_s is None:
                        first_token_s = time.perf_counter() - started
                    output += chunk
                    if isinstance(thinking_chunk, str):
                        if thinking_chunk and first_token_s is None:
                            first_token_s = time.perf_counter() - started
                        thinking += thinking_chunk
                    if on_chunk and (chunk or thinking_chunk):
                        on_chunk(chunk or thinking_chunk)
                    if item.get("done"):
                        final = item
    finally:
        stop.set()
        thread.join(timeout=2)
    wall = time.perf_counter() - started
    eval_count = int(final.get("eval_count", 0))
    prompt_count = int(final.get("prompt_eval_count", 0))
    eval_ns = int(final.get("eval_duration", 0))
    prompt_ns = int(final.get("prompt_eval_duration", 0))
    return {
        "model": model, "output": output or thinking,
        "ttft_s": round(first_token_s, 3) if first_token_s is not None else None,
        "total_time_s": round(wall, 3),
        "output_tokens": eval_count, "prompt_tokens": prompt_count,
        "generation_tokens_per_second": round(eval_count / (eval_ns / 1e9), 2) if eval_ns else None,
        "wall_tokens_per_second": round(eval_count / wall, 2) if wall else None,
        "prompt_tokens_per_second": round(prompt_count / (prompt_ns / 1e9), 2) if prompt_ns else None,
        "load_time_s": round(final.get("load_duration", 0) / 1e9, 3),
        "hardware": samples,
        "hardware_peak": {
            "cpu_percent": max((x["cpu_percent"] for x in samples), default=0),
            "ram_used_mb": max((x["ram_used_mb"] for x in samples), default=0),
            "gpu_utilization_percent": max((x["gpu"].get("utilization_percent", 0) for x in samples), default=0)
        },
        "finished_at": datetime.now(timezone.utc).isoformat()
    }


def benchmark_result(model: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = ["ttft_s", "total_time_s", "generation_tokens_per_second",
               "wall_tokens_per_second", "prompt_tokens_per_second", "load_time_s"]
    averages = {k: round(sum(x[k] for x in results if x[k] is not None) /
                         max(1, sum(1 for x in results if x[k] is not None)), 3)
                for k in numeric}
    return {"model": model, "runs": results, "averages": averages,
            "run_count": len(results)}

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

@app.get("/api/health")
def health():
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/version", timeout=3)
        r.raise_for_status()
        return {"ok": True, "ollama": r.json(), "ollama_url": OLLAMA_URL}
    except Exception as e:
        return {"ok": False, "error": str(e), "ollama_url": OLLAMA_URL}

@app.get("/api/models")
def models():
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        r.raise_for_status()
        data = r.json().get("models", [])
        return [{"name": m.get("name"), "size_bytes": m.get("size", 0),
                 "size_gb": round(m.get("size", 0) / 1e9, 2),
                 "parameter_size": m.get("details", {}).get("parameter_size"),
                 "quantization": m.get("details", {}).get("quantization_level"),
                 "family": m.get("details", {}).get("family")} for m in data]
    except Exception as e:
        raise HTTPException(503, f"Não foi possível consultar o Ollama: {e}")

@app.get("/api/system")
def system():
    return {"platform": platform.platform(), "python": platform.python_version(),
            "cpu_count": psutil.cpu_count(logical=True), "ram_total_gb": round(psutil.virtual_memory().total/1e9, 2),
            "hardware": hardware_snapshot(), "ollama_url": OLLAMA_URL}

@app.post("/api/benchmark")
def benchmark(req: BenchRequest):
    if not benchmark_lock.acquire(blocking=False):
        raise HTTPException(409, "Já existe um benchmark em execução. Aguarde terminar.")
    try:
        # Validate model name against local inventory.
        available = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10).json().get("models", [])
        if req.model not in [m.get("name") for m in available]:
            raise HTTPException(404, f"Modelo '{req.model}' não encontrado no Ollama.")
        results = []
        for _ in range(req.runs):
            results.append(run_once(req.model, req.prompt, req.temperature, req.num_predict))
        return benchmark_result(req.model, results)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Falha na comunicação com Ollama: {e}")
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    finally:
        benchmark_lock.release()


@app.post("/api/benchmark/stream")
def benchmark_stream(req: BenchRequest):
    def events():
        if not benchmark_lock.acquire(blocking=False):
            yield f"event: error\ndata: {json.dumps({'message': 'Já existe um benchmark em execução. Aguarde terminar.'}, ensure_ascii=False)}\n\n"
            return

        messages: Queue[dict[str, Any]] = Queue()
        try:
            available = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10).json().get("models", [])
            if req.model not in [m.get("name") for m in available]:
                yield f"event: error\ndata: {json.dumps({'message': f'Modelo {req.model!r} não encontrado no Ollama.'}, ensure_ascii=False)}\n\n"
                return

            def execute() -> None:
                try:
                    results = []
                    for run_number in range(req.runs):
                        result = run_once(
                            req.model,
                            req.prompt,
                            req.temperature,
                            req.num_predict,
                            on_chunk=lambda chunk: messages.put({
                                "event": "chunk", "run": run_number + 1, "text": chunk
                            }),
                        )
                        results.append(result)
                    messages.put({"event": "result", "data": benchmark_result(req.model, results)})
                except (httpx.HTTPError, RuntimeError) as error:
                    messages.put({"event": "error", "message": str(error)})
                finally:
                    messages.put({"event": "complete"})

            worker = threading.Thread(target=execute, daemon=True)
            worker.start()
            while True:
                message = messages.get()
                event = message["event"]
                if event == "chunk":
                    payload = {"run": message["run"], "text": message["text"]}
                elif event == "result":
                    payload = message["data"]
                else:
                    payload = {"message": message.get("message", "")}
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if event == "complete":
                    break
        except httpx.HTTPError as error:
            yield f"event: error\ndata: {json.dumps({'message': f'Falha na comunicação com Ollama: {error}'}, ensure_ascii=False)}\n\n"
        finally:
            benchmark_lock.release()

    return StreamingResponse(events(), media_type="text/event-stream")
