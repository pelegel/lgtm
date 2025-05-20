
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import httpx
import asyncio
import json

app = FastAPI()
VLLM_API_URL = "http://localhost:8000/v1/chat/completions"
VLLM_METRICS_URL = "http://localhost:8000/metrics"  # vLLM metrics endpoint
MODEL_NAME = "gaunernst/gemma-3-12b-it-qat-autoawq"

running_requests = []
waiting_requests = []

async def get_vllm_request_metrics():
    """Query vLLM metrics endpoint and extract running/waiting request counts"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(VLLM_METRICS_URL)
            metrics_text = response.text
            
            running_requests = 0
            waiting_requests = 0
            
            # Parse metrics to find running and waiting request counts using the correct metric names
            for line in metrics_text.split('\n'):
                if "vllm:num_requests_running" in line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 2:
                        running_requests = int(float(parts[-1]))
                elif "vllm:num_requests_waiting" in line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 2:
                        waiting_requests = int(float(parts[-1]))
            
            return running_requests, waiting_requests
    except Exception as e:
        print(f"Error fetching metrics: {e}")
        return None, None

async def stream_vllm_response(messages):
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True
    }
    
    # Get metrics before sending the request
    running, waiting = await get_vllm_request_metrics()
    print(f"Before request - Running requests: {running}, Waiting requests: {waiting}")
    
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", VLLM_API_URL, headers=headers, json=payload) as response:
            # Get metrics right after the request starts
            running, waiting = await get_vllm_request_metrics()
            print(f"Request started - Running requests: {running}, Waiting requests: {waiting}")
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    chunk = line.removeprefix("data: ").strip()
                    if chunk == "[DONE]":
                        # Get metrics at the end of response generation
                        running, waiting = await get_vllm_request_metrics()
                        print(f"Request completed - Running requests: {running}, Waiting requests: {waiting}")

                        with open(f"/workspace/running.txt", "a") as f:
                            f.write(f"{running}\n")

                        with open(f"/workspace/waiting.txt", "a") as f:
                            f.write(f"{waiting}\n")
                            
                        yield "data: [DONE]\n\n"
                        break
                    yield f"data: {chunk}\n\n"
                await asyncio.sleep(0.01)  # Yield control

@app.post("/stream")
async def stream_endpoint(request: Request):
    body = await request.json()
    messages = body["messages"]
    return StreamingResponse(stream_vllm_response(messages), media_type="text/event-stream")
