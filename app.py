import streamlit as st
import requests
import json

# Backend streaming API URL
STREAM_URL = "http://localhost:8090/stream"  # matches your FastAPI server address


SYSTEM_PROMPT = """אתה עוזר בינה מלאכותית שמטרתו לספק מידע מדויק ואמין בשפה העברית. ענה באופן ברור, מדויק, ומבוסס על עובדות בלבד. אל תנחש – אם אינך בטוח בתשובה, כתוב שאתה לא יודע או שהמידע חסר."""

# Keep chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]}]
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

st.title("ChatPLG")

# Display chat messages from history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        rtl_text = f'<div dir="rtl" style="text-align: right;">{msg["content"]}</div>'
        st.markdown(rtl_text, unsafe_allow_html=True)


# User input
if prompt := st.chat_input("כתוב שאלה כאן..."):

    # Append user message to messages and chat_history
    user_message = {"role": "user", "content": [{"type": "text", "text": prompt}]}
    st.session_state.messages.append(user_message)
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    rtl_user = f'<div dir="rtl" style="text-align: right;">{prompt}</div>'
    st.chat_message("user").markdown(rtl_user, unsafe_allow_html=True)
    
    # Prepare to collect full assistant response
    response_collector = []

    def stream_generator():
        for partial_response in stream_response(st.session_state.messages):
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
