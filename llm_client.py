"""
llm_client.py — Unified LLM client supporting both Ollama (local) and OpenRouter (cloud).

Usage:
    from llm_client import ask_llm, stream_llm

    # Non-streaming:
    response = ask_llm(messages, system_prompt)

    # Streaming (yields chunks):
    for chunk in stream_llm(messages, system_prompt):
        print(chunk, end='', flush=True)
"""

import json
import time
import requests
import config


def _get_llm_config():
    """Get the active LLM configuration based on current provider."""
    provider = getattr(config, 'PROVIDER', 'ollama')
    if provider == 'openrouter':
        return {
            'base_url': config.OPENROUTER_BASE_URL,
            'model': config.openrouter_model,
            'api_key': config.get_api_key('openrouter'),
            'context_length': config.get_active_context_length(),
            'is_openrouter': True,
        }
    else:
        return {
            'base_url': config.base_url,
            'model': config.model,
            'api_key': None,
            'context_length': config.context_length,
            'is_openrouter': False,
        }


def _build_headers(cfg):
    """Build HTTP headers for the LLM API call."""
    headers = {'Content-Type': 'application/json'}
    if cfg['is_openrouter'] and cfg['api_key']:
        headers['Authorization'] = f"Bearer {cfg['api_key']}"
        headers['HTTP-Referer'] = 'http://localhost:5000'
        headers['X-Title'] = 'Dungeon Master AI'
    return headers


def _build_payload(messages, system_prompt, stream, cfg):
    """Build the API payload for the LLM call."""
    model_name = cfg['model']

    if cfg['is_openrouter']:
        # OpenRouter uses OpenAI-compatible format
        # Strip 'openrouter/' prefix if present — OpenRouter routes by full name
        payload = {
            'model': model_name,
            'messages': messages,
            'stream': stream,
            'max_tokens': config.num_predict,
            'temperature': config.temp,
        }
        # Add system message as first message if provided
        if system_prompt:
            payload['messages'] = [
                {'role': 'system', 'content': system_prompt}
            ] + list(messages)
    else:
        # Ollama format
        payload = {
            'model': model_name,
            'messages': messages,
            'system': system_prompt,
            'stream': stream,
            'think': False,
            'options': {
                'num_ctx': cfg['context_length'],
                'temperature': config.temp,
                'num_predict': config.num_predict,
            }
        }
    return payload


def _get_chat_endpoint(cfg):
    """Get the chat completion endpoint URL."""
    if cfg['is_openrouter']:
        return f"{cfg['base_url']}/chat/completions"
    else:
        return f"{cfg['base_url']}/api/chat"


def ask_llm(messages, system_prompt="", timeout=120):
    """
    Send a non-streaming request to the LLM.
    Returns the full response text.
    """
    cfg = _get_llm_config()
    headers = _build_headers(cfg)
    payload = _build_payload(messages, system_prompt, False, cfg)
    endpoint = _get_chat_endpoint(cfg)

    print(f"🐞 [LLM] Provider: {'OpenRouter' if cfg['is_openrouter'] else 'Ollama'}, Model: {cfg['model']}")

    response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()

    result = response.json()

    if cfg['is_openrouter']:
        # OpenRouter returns OpenAI-compatible format
        return result.get('choices', [{}])[0].get('message', {}).get('content', '')
    else:
        # Ollama format
        return result.get('message', {}).get('content', '')


def stream_llm(messages, system_prompt, timeout=120):
    """
    Send a streaming request to the LLM.
    Yields (text_chunk, is_done) tuples.
    """
    cfg = _get_llm_config()
    headers = _build_headers(cfg)
    payload = _build_payload(messages, system_prompt, True, cfg)
    endpoint = _get_chat_endpoint(cfg)

    print(f"🐞 [LLM] Provider: {'OpenRouter' if cfg['is_openrouter'] else 'Ollama'}, Model: {cfg['model']}")

    response = requests.post(endpoint, json=payload, headers=headers, stream=True, timeout=timeout)
    response.raise_for_status()

    if cfg['is_openrouter']:
        # OpenRouter streaming (SSE format, OpenAI-compatible)
        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode('utf-8') if isinstance(line, bytes) else line
            if line_str.startswith('data: '):
                data_str = line_str[6:]
                if data_str.strip() == '[DONE]':
                    yield '', True
                    continue
                try:
                    data = json.loads(data_str)
                    choices = data.get('choices', [])
                    if choices:
                        delta = choices[0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            yield content, False
                except json.JSONDecodeError:
                    pass
            elif line_str.strip() == '[DONE]':
                yield '', True
    else:
        # Ollama streaming (newline-delimited JSON)
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            message = chunk.get('message', {})
            content = message.get('content', '')
            if content:
                yield content, False
            if chunk.get('done'):
                yield '', True


def ask_llm_full(messages, system_prompt, timeout=120):
    """
    Streaming request that collects and returns the full response.
    Also prints chunks to stdout in real-time.
    """
    start = time.time()
    full_response = ""
    first_chunk_time = None

    print("\n🧙 GM: ", end="", flush=True)

    for content, done in stream_llm(messages, system_prompt, timeout):
        if first_chunk_time is None and content:
            first_chunk_time = time.time() - start
        if content:
            print(content, end="", flush=True)
            full_response += content
        if done:
            break

    elapsed = time.time() - start
    print(f"\n\n⏱️  Toplam: {elapsed:.2f}s | İlk token: {first_chunk_time:.2f}s" if first_chunk_time else f"\n\n⏱️  Toplam: {elapsed:.2f}s")
    return full_response
