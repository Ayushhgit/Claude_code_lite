import os
import time
from dotenv import load_dotenv

load_dotenv()

MAX_RETRIES = 5

def generate(messages, tools=None):
    """
    Unified LLM generation function that routes to either Groq or Gemini
    based on the PROVIDER environment variable (default: groq).
    """
    provider = os.getenv("PROVIDER", "groq").lower()
    
    if provider == "gemini":
        return _generate_gemini(messages, tools)
    else:
        return _generate_groq(messages, tools)

def _generate_groq(messages, tools):
    from groq import Groq
    
    client = Groq(
        api_key=os.getenv("GROQ_API_KEY"),
        max_retries=0,
    )
    model = os.getenv("MODEL", "llama3-70b-8192")
    
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.2,
                messages=messages,
                **kwargs
            )
            message = response.choices[0].message
            
            if not tools:
                return message.content.strip() if message.content else ""
                
            return message
        except Exception as e:
            error_str = str(e).lower()
            if any(code in error_str for code in ['429', 'rate_limit', 'rate limit', '503', '502', '500']):
                if attempt < MAX_RETRIES:
                    wait = min(2 ** attempt * 2, 60)
                    print(f" Groq rate limited (attempt {attempt+1}/{MAX_RETRIES}). Waiting {wait}s...")
                    time.sleep(wait)
                    continue
            raise
    
    raise Exception("Max retries exceeded for Groq LLM call")

def _generate_gemini(messages, tools):
    from openai import OpenAI
    
    # Gemini provides an OpenAI-compatible endpoint
    client = OpenAI(
        api_key=os.getenv("GEMINI_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        max_retries=0,
    )
    model = os.getenv("MODEL", "gemini-2.5-flash")
    
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
        # For Gemini compatibility with OpenAI SDK, tool_choice needs to be explicit or omitted
        # 'auto' is default in OpenAI, but leaving it omitted usually works best for Gemini OpenAI endpoint
        
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.2,
                messages=messages,
                **kwargs
            )
            message = response.choices[0].message
            
            if not tools:
                return message.content.strip() if message.content else ""
                
            return message
        except Exception as e:
            error_str = str(e).lower()
            if any(code in error_str for code in ['429', 'rate_limit', 'rate limit', '503', '502', '500']):
                if attempt < MAX_RETRIES:
                    wait = min(2 ** attempt * 2, 60)
                    print(f" Gemini rate limited (attempt {attempt+1}/{MAX_RETRIES}). Waiting {wait}s...")
                    time.sleep(wait)
                    continue
            raise
            
    raise Exception("Max retries exceeded for Gemini LLM call")
