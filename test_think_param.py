import httpx
import json
import time

def test_think():
    print("Testing with think=False in options vs payload vs chat...")
    client = httpx.Client(timeout=30.0)
    # Test 1: think=False in payload (Ollama v0.5+ supports think parameter)
    for param in [{"think": False}, {"options": {"stop": ["<think>"]}}, {}]:
        t0 = time.time()
        print(f"\nTesting param: {param}")
        try:
            payload = {
                "model": "qwen3:4b",
                "prompt": "Respond with single word: READY",
                "stream": True,
            }
            if "options" in param:
                payload["options"] = param["options"]
            else:
                payload.update(param)
            
            with client.stream("POST", "http://127.0.0.1:11434/api/generate", json=payload) as r:
                think_chars = 0
                resp_chars = 0
                for line in r.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("thinking"):
                        think_chars += len(data["thinking"])
                    if data.get("response"):
                        resp_chars += len(data["response"])
                    if data.get("done"):
                        break
                print(f"Elapsed: {time.time()-t0:.2f}s | think chars: {think_chars} | resp chars: {resp_chars}")
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    test_think()
