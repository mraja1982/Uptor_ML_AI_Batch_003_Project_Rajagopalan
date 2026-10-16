import time
import requests


OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "llama3.2:1b"


prompt = (
    "For server srv-web-prod-01, "
    "give 3 proactive CPU remediation steps. "
    "Keep the answer concise."
)


payload = {
    "model": OLLAMA_MODEL,
    "prompt": prompt,
    "stream": False,
    "keep_alive": "10m",
    "options": {
        "temperature": 0.2,
        "num_predict": 100,
    },
}


print("========================================")
print("OLLAMA PYTHON CONNECTIVITY TEST")
print("========================================")

print(f"URL   : {OLLAMA_URL}")
print(f"MODEL : {OLLAMA_MODEL}")
print(f"PROMPT: {len(prompt)} characters")
print()
print("Calling Ollama...")


start = time.perf_counter()

try:
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json=payload,
        timeout=(5, 30),
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    print(
        f"Response time : {elapsed:.3f} seconds"
    )

    print(
        f"HTTP status   : {response.status_code}"
    )

    response.raise_for_status()

    data = response.json()

    print()
    print("Ollama response:")
    print(
        data.get(
            "response",
            "",
        )
    )

except Exception as exc:

    elapsed = (
        time.perf_counter()
        - start
    )

    print(
        f"FAILED after {elapsed:.3f} seconds"
    )

    print(
        f"Error: {type(exc).__name__}: {exc}"
    )