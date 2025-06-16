from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import httpx
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import time # For latency measurement
import uuid # To generate unique request IDs

app = FastAPI()

# --- Logging Configuration for FastAPI Server ---
LOG_DIR = "/var/log/chatbot"
SERVER_LOG_FILE = os.path.join(LOG_DIR, "fastapi_server.log")

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Custom JSON formatter (can be shared with app.py if put in a common file)
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger_name": record.name,
            "filename": record.filename,
            "lineno": record.lineno,
            "process": record.process,
            "thread": record.thread,
            # Add custom fields if they exist in the record
            **getattr(record, 'extra_data', {})
        }
        return json.dumps(log_entry, ensure_ascii=False)

server_logger = logging.getLogger("fastapi_server")
server_logger.setLevel(logging.INFO)

# File handler for server logs
file_handler = RotatingFileHandler(
    SERVER_LOG_FILE,
    maxBytes=10 * 1024 * 1024, # 10 MB per file
    backupCount=5 # Keep 5 backup files
)
file_handler.setFormatter(JsonFormatter())
server_logger.addHandler(file_handler)

# Console handler for server logs during development (optional for production)
# console_handler = logging.StreamHandler()
# console_handler.setFormatter(JsonFormatter())
# server_logger.addHandler(console_handler)
# -----------------------------------------------

VLLM_API_URL = "http://localhost:8000/v1/chat/completions"
VLLM_METRICS_URL = "http://localhost:8000/metrics"  # vLLM metrics endpoint
MODEL_NAME = "gaunernst/gemma-3-12b-it-qat-autoawq"

# You no longer need these global lists, as we'll log metrics instead
# running_requests = []
# waiting_requests = []

async def get_vllm_request_metrics(request_id):
    """
    Query vLLM metrics endpoint and extract running/waiting request counts.
    Logs the metrics.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(VLLM_METRICS_URL)
            response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
            metrics_text = response.text
            
            running_requests_count = 0
            waiting_requests_count = 0
            
            # Parse metrics to find running and waiting request counts using the correct metric names
            for line in metrics_text.split('\n'):
                if "vllm_num_requests_running" in line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            running_requests_count = int(float(parts[-1]))
                        except ValueError:
                            server_logger.warning(f"Could not parse running_requests_count from line: {line}", extra={"extra_data": {"request_id": request_id}})
                elif "vllm_num_requests_waiting" in line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            waiting_requests_count = int(float(parts[-1]))
                        except ValueError:
                            server_logger.warning(f"Could not parse waiting_requests_count from line: {line}", extra={"extra_data": {"request_id": request_id}})
            
            server_logger.info("vLLM metrics fetched", extra={"extra_data": {
                "request_id": request_id,
                "vllm_running_requests": running_requests_count,
                "vllm_waiting_requests": waiting_requests_count,
                "event_type": "vllm_metrics_query"
            }})
            return running_requests_count, waiting_requests_count
    except httpx.RequestError as e:
        server_logger.error(f"Error fetching vLLM metrics: {e}", extra={"extra_data": {
            "request_id": request_id,
            "event_type": "vllm_metrics_error"
        }})
        return None, None

async def stream_vllm_response(messages, request_id):
    """
    Streams response from vLLM and logs interaction details.
    """
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True
    }

    server_logger.info("Calling vLLM API", extra={"extra_data": {
        "request_id": request_id,
        "vllm_api_url": VLLM_API_URL,
        "vllm_model": MODEL_NAME,
        "event_type": "vllm_api_call",
        "initial_messages": messages[-1] # Log only the latest user message to avoid verbosity
    }})

    start_time = time.perf_counter()

    # Get metrics before sending the request
    # Note: Metrics here reflect the state *before* this specific request is processed by vLLM
    running_before, waiting_before = await get_vllm_request_metrics(request_id)
    server_logger.info(f"Metrics before vLLM request. Running: {running_before}, Waiting: {waiting_before}", extra={"extra_data": {
        "request_id": request_id,
        "vllm_running_before": running_before,
        "vllm_waiting_before": waiting_before,
        "event_type": "metrics_before_vllm_request"
    }})
    
    total_output_tokens = 0

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", VLLM_API_URL, headers=headers, json=payload) as response:
                response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
                
                # Get metrics right after the request starts (might be slightly delayed for actual processing start)
                # This might show the request as already running or waiting depending on vLLM's internal scheduling
                running_after_init, waiting_after_init = await get_vllm_request_metrics(request_id)
                server_logger.info(f"Metrics after vLLM stream initiated. Running: {running_after_init}, Waiting: {waiting_after_init}", extra={"extra_data": {
                    "request_id": request_id,
                    "vllm_running_after_init": running_after_init,
                    "vllm_waiting_after_init": waiting_after_init,
                    "event_type": "metrics_after_stream_init"
                }})

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line.removeprefix("data: ").strip()
                        if chunk == "[DONE]":
                            end_time = time.perf_counter()
                            latency_ms = (end_time - start_time) * 1000
                            
                            server_logger.info("vLLM streaming complete", extra={"extra_data": {
                                "request_id": request_id,
                                "total_latency_ms": latency_ms,
                                "total_output_tokens": total_output_tokens,
                                "event_type": "vllm_stream_done"
                            }})

                            # Get final metrics after response generation is finished
                            running_after, waiting_after = await get_vllm_request_metrics(request_id)
                            server_logger.info(f"Metrics after vLLM request completion. Running: {running_after}, Waiting: {waiting_after}", extra={"extra_data": {
                                "request_id": request_id,
                                "vllm_running_after": running_after,
                                "vllm_waiting_after": waiting_after,
                                "event_type": "metrics_after_vllm_completion"
                            }})
                            
                            # Removed writing to running.txt/waiting.txt as this data should be logged
                            # and ideally sent to Prometheus for time-series analysis.
                            # with open(f"/workspace/running.txt", "a") as f:
                            #     f.write(f"{running}\n")
                            # with open(f"/workspace/waiting.txt", "a") as f:
                            #     f.write(f"{waiting}\n")
                                    
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            data = json.loads(chunk)
                            delta = data["choices"][0]["delta"].get("content", "")
                            # If token count is available from vLLM, extract it here
                            # total_output_tokens += data["token_count"] # Example if vLLM provides it per chunk
                            
                            # server_logger.debug("Received vLLM chunk", extra={"extra_data": {
                            #     "request_id": request_id,
                            #     "delta_content": delta,
                            #     "event_type": "vllm_chunk"
                            # }})
                            yield f"data: {chunk}\n\n"
                        except json.JSONDecodeError as e:
                            server_logger.error(f"JSON decoding error from vLLM: {e}, Chunk: {chunk}", extra={"extra_data": {
                                "request_id": request_id,
                                "raw_vllm_chunk": chunk,
                                "event_type": "vllm_json_error"
                            }})
                            continue
                    else:
                        if line: # Log non-data lines from vLLM for debugging
                            server_logger.warning(f"Non-data line from vLLM: {line.decode('utf-8')}", extra={"extra_data": {
                                "request_id": request_id,
                                "raw_line": line.decode('utf-8'),
                                "event_type": "vllm_non_data_line"
                            }})
                    await asyncio.sleep(0.01)  # Yield control for responsiveness
    except httpx.RequestError as e:
        server_logger.error(f"Error calling vLLM API: {e}", extra={"extra_data": {
            "request_id": request_id,
            "event_type": "vllm_api_error"
        }})
        # Propagate error to frontend gracefully
        yield f"data: {json.dumps({'choices': [{'delta': {'content': f'Error from LLM backend: {e}'}}]})}\n\n"
        yield "data: [DONE]\n\n"

@app.post("/stream")
async def stream_endpoint(request: Request):
    """
    Main endpoint for the Streamlit app to communicate with.
    """
    request_id = str(uuid.uuid4()) # Generate a unique ID for this full interaction

    # Log the incoming request to the FastAPI server
    server_logger.info("Incoming request to FastAPI stream endpoint", extra={"extra_data": {
        "request_id": request_id,
        "client_ip": request.client.host,
        "event_type": "incoming_request"
    }})
    
    body = await request.json()
    messages = body["messages"]

    # You can log the full messages list if needed, but be mindful of verbosity
    # server_logger.debug("Received messages payload", extra={"extra_data": {
    #     "request_id": request_id,
    #     "messages_payload": messages
    # }})
    
    return StreamingResponse(stream_vllm_response(messages, request_id), media_type="text/event-stream")

