# Hosting Gemma3 12b model using vLLM #

This inference is based on "gaunernst/gemma-3-12b-it-qat-autoawq" model from HuggingFace.

**Docker options:**
```python
-p 1111:1111 -p 8080:8080 -p 8090:8090 -p 8000:8000 -p 8265:8265 -p 8501:8501 -e OPEN_BUTTON_PORT=1111 -e OPEN_BUTTON_TOKEN=1 -e JUPYTER_DIR=/ -e DATA_DIRECTORY=/workspace/ -e PORTAL_CONFIG="localhost:1111:11111:/:Instance Portal|localhost:8000:18000:/docs:vLLM API|localhost:8265:28265:/:Ray Dashboard|localhost:8080:18080:/:Jupyter|localhost:8080:8080:/terminals/1:Jupyter Terminal" -e VLLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Llama-8B -e VLLM_ARGS="--max-model-len 8192 --enforce-eager --download-dir /workspace/models --host 127.0.0.1 --port 18000" -e RAY_ARGS="--head --port 6379  --dashboard-host 127.0.0.1 --dashboard-port 28265" -e RAY_ADDRESS=127.0.0.1:6379 -e USE_ALL_GPUS=true
```

**Create venv and install requirements:**
```python
python -m venv vllm_venv
source vllm_venv/bin/activate
python -m pip install -r requirements.txt
```

**Start the vLLM server:**
```python
python3 -m vllm.entrypoints.openai.api_server   --model gaunernst/gemma-3-12b-it-qat-autoawq --max-model-len 131072   --tensor-parallel-size 2 | grep -Ev "Received request chatcmpl|Added request chatcmpl|HTTP/1.1\" 200 OK"
```
The vLLM server will be ready for launch when the following logs appear:
```
INFO:     Started server process [1490]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO 04-22 13:22:12 [loggers.py:87] Engine 000: Avg prompt throughput: 0.0 tokens/s, Avg generation throughput: 0.0 tokens/s, Running: 0 reqs, Waiting: 0 reqs, GPU KV cache usage: 0.0%, Prefix cache hit rate: 0.0%
```



 **Start the FastAPI server:**
```python
uvicorn server:app --host 0.0.0.0 --port 8090
```

The FastAPI server will be ready for launch when the following logs appear:
```
INFO:     Started server process [2887]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8090 (Press CTRL+C to quit)
```


**Run the app:**
```python
 streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.fileWatcherType=none
```

**In the browser, open:**
```python
http://172.81.127.5:31855
```
or the port on vast.ai that is mapped to 8501/tcp
172.81.127.5:31855 -> 8501/tcp
