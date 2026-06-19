# =============================================================================
# agents/llm_client.py — Central LLM routing layer
#
# Provider priority:
#   1. Gateway  (chat_api_url set)  → gpu.idhub.ng/chat  — gpt-4o-mini via Azure
#   2. RunPod   (LLM_PROVIDER=runpod)
#   3. Ollama   (default, local)
#
# Model tiers (RunPod only — gateway and Ollama ignore tier):
#   "light"   → 7B  endpoint  — classification, CDI checks, harmonisation
#   "heavy"   → 14B endpoint  — extraction, gap analysis, policy drafting
#
# Usage:
#   from agents.llm_client import llm_generate, check_llm_connectivity
#   text = await llm_generate(prompt, tier="heavy", max_tokens=2000)
# =============================================================================

import asyncio
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_RUNPOD_BASE = "https://api.runpod.ai/v2"


# =============================================================================
#  Public interface
# =============================================================================

async def llm_generate(
    prompt: str,
    tier: str = "light",
    *,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    top_p: float = 0.9,
    repeat_penalty: float = 1.2,
    json_mode: bool = False,
    system_prompt: str = "",
) -> str:
    """
    Generate text from the configured LLM provider.

    Args:
        prompt:         Full prompt string (sent as user message to gateway).
        tier:           "light" or "heavy". Ignored by gateway and ollama.
        max_tokens:     Maximum tokens to generate.
        temperature:    Sampling temperature.
        top_p:          Nucleus sampling p.
        repeat_penalty: Repetition penalty (Ollama only).
        json_mode:      Hint model to return JSON.
        system_prompt:  Optional system message override (gateway only).

    Returns:
        Generated text, or "" on failure.
    """
    if settings.chat_api_url:
        return await _gateway_generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=system_prompt,
        )
    if settings.llm_provider == "runpod":
        return await _runpod_generate(
            prompt, tier,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )
    return await _ollama_generate(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        repeat_penalty=repeat_penalty,
        json_mode=json_mode,
    )


async def check_llm_connectivity() -> dict:
    """Health check — delegates to the active provider."""
    if settings.chat_api_url:
        return await _check_gateway()
    if settings.llm_provider == "runpod":
        return await _check_runpod()
    return await _check_ollama()


# =============================================================================
#  Gateway backend  (gpu.idhub.ng — Azure OpenAI via custom proxy)
# =============================================================================

_GATEWAY_SYSTEM = (
    "You are a compliance and document analysis assistant for Dragnet Solutions. "
    "Follow the instructions in the user message exactly. "
    "Return only valid JSON when asked for JSON — no explanation, no markdown fences."
)


async def _gateway_generate(
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    system_prompt: str = "",
) -> str:
    headers = {
        "Authorization": f"Bearer {settings.inference_api_key}",
        "Content-Type":  "application/json",
    }
    messages = [
        {"role": "system", "content": system_prompt or _GATEWAY_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    payload = {
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            resp = await client.post(settings.chat_api_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Standard OpenAI response shape
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            return str(msg.get("content", "")).strip()

        # Fallback — some proxies return {"content": "..."}
        return str(data.get("content") or data.get("text") or "").strip()

    except Exception as exc:
        logger.warning(f"Gateway generate failed: {exc}")
        return ""


async def _check_gateway() -> dict:
    try:
        result = await _gateway_generate(
            "Reply with the single word: ok",
            max_tokens=5,
            temperature=0.0,
        )
        ok = bool(result)
        return {
            "status":   "ok" if ok else "error",
            "provider": "gateway",
            "model":    "gpt-4o-mini",
            "url":      settings.chat_api_url,
        }
    except Exception as exc:
        return {
            "status":   "error",
            "provider": "gateway",
            "detail":   str(exc),
        }


# =============================================================================
#  Ollama backend
# =============================================================================

async def _ollama_generate(
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    repeat_penalty: float,
    json_mode: bool,
) -> str:
    payload: dict = {
        "model":  settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature":    temperature,
            "top_p":          top_p,
            "repeat_penalty": repeat_penalty,
            "num_predict":    max_tokens,
        },
    }
    if json_mode:
        payload["format"] = "json"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_timeout, connect=10.0)
        ) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.warning(f"Ollama generate failed: {exc}")
        return ""


async def _check_ollama() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return {
                "status":           "ok",
                "provider":         "ollama",
                "model":            settings.ollama_model,
                "model_available":  any(settings.ollama_model in m for m in models),
                "available_models": models,
            }
    except httpx.ConnectError:
        return {
            "status":   "error",
            "provider": "ollama",
            "detail":   (
                f"Cannot connect to Ollama at {settings.ollama_base_url}. "
                "Run: ollama serve"
            ),
        }
    except Exception as exc:
        return {"status": "error", "provider": "ollama", "detail": str(exc)}


# =============================================================================
#  RunPod backend
# =============================================================================

async def _runpod_generate(
    prompt: str,
    tier: str,
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
) -> str:
    endpoint_id = (
        settings.runpod_light_endpoint_id
        if tier == "light"
        else settings.runpod_heavy_endpoint_id
    )
    url = f"{_RUNPOD_BASE}/{endpoint_id}/runsync"
    headers = {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "input": {
            "prompt": prompt,
            "sampling_params": {
                "max_tokens":  max_tokens,
                "temperature": temperature,
                "top_p":       top_p,
            },
        }
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.runpod_timeout, connect=10.0)
        ) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status")

            # Completed inline — common when worker is warm
            if not status or status == "COMPLETED":
                logger.debug(f"RunPod {tier} COMPLETED response keys={list(data.keys())} output_type={type(data.get('output')).__name__} output_preview={str(data.get('output'))[:300]}")
                return _extract_runpod_text(data)
            
            

            # runsync sync-timeout hit — job is queued/running, poll until done
            job_id = data.get("id")
            if status in ("IN_PROGRESS", "IN_QUEUE") and job_id:
                poll_url = f"{_RUNPOD_BASE}/{endpoint_id}/status/{job_id}"
                logger.info(f"RunPod {tier} job {job_id} is {status} — polling")
                for _ in range(120):  # up to 10 min (120 × 5s)
                    await asyncio.sleep(5)
                    poll_resp = await client.get(poll_url, headers=headers)
                    poll_resp.raise_for_status()
                    poll_data = poll_resp.json()
                    poll_status = poll_data.get("status")
                    if poll_status == "COMPLETED":
                        return _extract_runpod_text(poll_data)
                    if poll_status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                        logger.warning(f"RunPod {tier} job {job_id} ended with {poll_status}")
                        return ""
                logger.warning(f"RunPod {tier} job {job_id} did not complete after 10 min of polling")
                return ""

            logger.warning(
                f"RunPod {tier} ({endpoint_id}) status={status}: "
                f"{data.get('error', '')}"
            )
            return ""

    except Exception as exc:
        logger.warning(f"RunPod {tier} ({endpoint_id}) generate failed: {exc}")
        return ""


def _extract_runpod_text(data: dict) -> str:
    """
    Parse RunPod runsync response — handles all common vLLM worker output shapes:
      Shape 1: output = [{"text": "..."}]                  (vLLM completion)
      Shape 2: output = {"choices": [{"text": "..."}]}     (OpenAI completion)
      Shape 3: output = {"choices": [{"message": ...}]}    (OpenAI chat)
      Shape 4: output = "plain string"                     (simple workers)
    """
    output = data.get("output")
    if output is None:
        return ""

    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, dict):
            # vLLM batch output: [{"choices": [{"text": "..."}]}]
            if "choices" in first:
                choices = first.get("choices") or []
                if choices:
                    c = choices[0]
                    if isinstance(c, dict):
                        if "message" in c:
                            return str(c["message"].get("content", "")).strip()
                        return str(c.get("text") or c.get("content", "")).strip()
            return str(first.get("text") or first.get("content") or "").strip()
        return str(first).strip()

    if isinstance(output, dict):
        choices = output.get("choices") or []
        if choices:
            c = choices[0]
            if isinstance(c, dict):
                if "message" in c:
                    return str(c["message"].get("content", "")).strip()
                return str(c.get("text") or c.get("content", "")).strip()
        if "text" in output:
            return str(output["text"]).strip()

    if isinstance(output, str):
        return output.strip()

    return ""


async def _check_runpod() -> dict:
    """Ping the light endpoint health route to verify API key and reachability."""
    endpoint_id = settings.runpod_light_endpoint_id
    url = f"{_RUNPOD_BASE}/{endpoint_id}/health"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {settings.runpod_api_key}"},
            )
        ok = resp.status_code < 500
        return {
            "status":          "ok" if ok else "error",
            "provider":        "runpod",
            "light_endpoint":  settings.runpod_light_endpoint_id,
            "heavy_endpoint":  settings.runpod_heavy_endpoint_id,
            "http_status":     resp.status_code,
        }
    except Exception as exc:
        return {
            "status":   "error",
            "provider": "runpod",
            "detail":   str(exc),
        }
