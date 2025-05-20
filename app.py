import streamlit as st
import requests
import json

# Backend streaming API URL
STREAM_URL = "http://localhost:8090/stream"  # matches your FastAPI server address

# Keep chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": [{"type": "text", "text": "תענה בבקשה על שאלות המשתמש בשפה העברית."}]}
    ]
    st.session_state.chat_history = []  # for UI display

def stream_response(messages):
    headers = {"Content-Type": "application/json"}
    with requests.post(STREAM_URL, json={"messages": messages}, headers=headers, stream=True) as r:
        for line in r.iter_lines():
            if line and line.startswith(b"data:"):
                chunk = line.lstrip(b"data: ").decode("utf-8").strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                    delta = data["choices"][0]["delta"].get("content", "")
                    yield delta
                except Exception:
                    continue

st.title("Hebrew Chatbot UI")

# Display chat messages from history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# User input
if prompt := st.chat_input("כתוב שאלה כאן..."):

    # Append user message to messages and chat_history
    user_message = {"role": "user", "content": [{"type": "text", "text": prompt}]}
    st.session_state.messages.append(user_message)
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    # Prepare to collect full assistant response
    response_collector = []

    def stream_generator():
        for partial_response in stream_response(st.session_state.messages):
            response_collector.append(partial_response)
            yield partial_response

    # Stream response to UI
    st.chat_message("assistant").write_stream(stream_generator())

    # Final full response
    assistant_response = "".join(response_collector)
    assistant_message = {"role": "assistant", "content": [{"type": "text", "text": assistant_response}]}
    st.session_state.messages.append(assistant_message)
    st.session_state.chat_history.append({"role": "assistant", "content": assistant_response})
