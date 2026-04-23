import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def generate(messages, tools=None):
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
        
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        temperature=0.2,
        messages=messages,
        **kwargs
    )
    message = response.choices[0].message
    
    # Return string if no tools were provided (for backwards compatibility with router/file_selector)
    if not tools:
        return message.content.strip() if message.content else ""
        
    return message