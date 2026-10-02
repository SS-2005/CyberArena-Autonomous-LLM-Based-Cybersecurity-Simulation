import httpx
import json
import time

def main():
    t0 = time.time()
    print("Connecting to Ollama...")
    client = httpx.Client(timeout=180.0)
    payload = {
        "model": "qwen3:4b",
        "prompt": "You are an agent. Respond with a JSON object: {\"thought\": \"checking status\", \"tool\": \"execute_command\", \"parameters\": {\"command\": \"uptime\"}}",
        "stream": True,
        "format": "json"
    }
    with client.stream("POST", "http://127.0.0.1:11434/api/generate", json=payload) as response:
        first_token_time = None
        accum = ""
        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            chunk = data.get("response", "")
            if chunk:
                if first_token_time is None:
                    first_token_time = time.time() - t0
                    print(f"Time to first token: {first_token_time:.2f}s")
                accum += chunk
                print(chunk, end="", flush=True)
            if data.get("done"):
                print(f"\nDone in {time.time()-t0:.2f}s! Total eval_count: {data.get('eval_count')}")
                break

if __name__ == "__main__":
    main()
