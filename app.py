import streamlit as st
import requests
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import uuid # To generate unique request IDs

# --- Logging Configuration for Streamlit App ---
LOG_DIR = "/var/log/chatbot"
APP_LOG_FILE = os.path.join(LOG_DIR, "streamlit_app.log")

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Custom JSON formatter
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
        return json.dumps(log_entry, ensure_ascii=False) # ensure_ascii=False for Hebrew characters

app_logger = logging.getLogger("streamlit_app")
app_logger.setLevel(logging.INFO)

# File handler for app logs
file_handler = RotatingFileHandler(
    APP_LOG_FILE,
    maxBytes=10 * 1024 * 1024, # 10 MB per file
    backupCount=5 # Keep 5 backup files
)
file_handler.setFormatter(JsonFormatter())
app_logger.addHandler(file_handler)

# If you also want to see logs in the console
# console_handler = logging.StreamHandler()
# console_handler.setFormatter(JsonFormatter())
# app_logger.addHandler(console_handler)
# -----------------------------------------------

# Backend streaming API URL
STREAM_URL = "http://localhost:8090/stream"  # matches your FastAPI server address


SYSTEM_PROMPT = """אתה עוזר בינה מלאכותית שמטרתו לספק מידע מדויק ואמין בשפה העברית. ענה באופן ברור, מדויק, ומבוסס על עובדות בלבד. אל תנחש – אם אינך בטוח בתשובה, כתוב שאתה לא יודע או שהמידע חסר."""

# Keep chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]}]
    st.session_state.chat_history = []  # for UI display

def stream_response(messages, request_id):
    """
    Streams response from the backend and logs each interaction.
    """
    headers = {"Content-Type": "application/json"}
    
    # Log the full request being sent to the backend
    app_logger.info("Sending request to backend", extra={"extra_data": {
        "request_id": request_id,
        "payload_messages": messages,
        "event_type": "backend_request"
    }})

    try:
        with requests.post(STREAM_URL, json={"messages": messages}, headers=headers, stream=True) as r:
            r.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
            for line in r.iter_lines():
                if line and line.startswith(b"data:"):
                    chunk = line.lstrip(b"data: ").decode("utf-8").strip()
                    if chunk == "[DONE]":
                        app_logger.info("Backend streaming complete", extra={"extra_data": {
                            "request_id": request_id,
                            "event_type": "backend_stream_done"
                        }})
                        break
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"].get("content", "")
                        
                        # Log each partial response chunk (optional, can be very verbose)
                        # app_logger.debug("Received chunk", extra={"extra_data": {
                        #     "request_id": request_id,
                        #     "delta": delta,
                        #     "event_type": "backend_chunk"
                        # }})
                        yield delta
                    except json.JSONDecodeError as e:
                        app_logger.error(f"JSON decoding error: {e}, Chunk: {chunk}", extra={"extra_data": {
                            "request_id": request_id,
                            "raw_chunk": chunk,
                            "event_type": "json_decode_error"
                        }})
                        continue
                else:
                    # Log non-data lines for debugging if necessary
                    if line:
                        app_logger.debug(f"Non-data line received: {line.decode('utf-8')}", extra={"extra_data": {
                            "request_id": request_id,
                            "event_type": "non_data_line"
                        }})
    except requests.exceptions.RequestException as e:
        app_logger.error(f"Error connecting to backend: {e}", extra={"extra_data": {
            "request_id": request_id,
            "event_type": "backend_connection_error"
        }})
        st.error(f"Connection error to backend: {e}. Please ensure the FastAPI server is running.")
        yield "" # Yield empty string to prevent further errors in Streamlit display

st.title("ChatPLG")

# Display chat messages from history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        rtl_text = f'<div dir="rtl" style="text-align: right;">{msg["content"]}</div>'
        st.markdown(rtl_text, unsafe_allow_html=True)


# User input
if prompt := st.chat_input("כתוב שאלה כאן..."):
    request_id = str(uuid.uuid4()) # Generate a unique ID for this full interaction

    # Log user message before adding to state
    app_logger.info("User query received", extra={"extra_data": {
        "request_id": request_id,
        "user_input": prompt,
        "event_type": "user_query"
    }})

    # Append user message to messages and chat_history
    user_message = {"role": "user", "content": [{"type": "text", "text": prompt}]}
    st.session_state.messages.append(user_message)
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    rtl_user = f'<div dir="rtl" style="text-align: right;">{prompt}</div>'
    st.chat_message("user").markdown(rtl_user, unsafe_allow_html=True)
    
    # Prepare to collect full assistant response
    response_collector = []

    def stream_generator():
        # Pass the unique request_id to the stream_response function
        for partial_response in stream_response(st.session_state.messages, request_id):
            response_collector.append(partial_response)
            yield partial_response

    # Stream response to UI
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        streamed_text = ""
        for token in stream_generator():
            streamed_text += token
            rtl_partial = f'<div dir="rtl" style="text-align: right;">{streamed_text}</div>'
            response_placeholder.markdown(rtl_partial, unsafe_allow_html=True)

    # Final full response
    assistant_response = "".join(response_collector)
    assistant_message = {"role": "assistant", "content": [{"type": "text", "text": assistant_response}]}
    st.session_state.messages.append(assistant_message)
    st.session_state.chat_history.append({"role": "assistant", "content": assistant_response})

    # Log the complete assistant response
    app_logger.info("Assistant response completed", extra={"extra_data": {
        "request_id": request_id,
        "assistant_response": assistant_response,
        "event_type": "assistant_response_complete"
    }})

