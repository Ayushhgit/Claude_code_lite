import os
import time
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(
    api_key=os.getenv("GROQ_API_KEY"),
    max_retries=0,  # We handle retries ourselves — the SDK's built-in retry hangs
)
model = os.getenv("MODEL")

MAX_RETRIES = 5

def generate(messages, tools=None):
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
            
            # Return string if no tools were provided (for backwards compatibility)
            if not tools:
                return message.content.strip() if message.content else ""
                
            return message
        except Exception as e:
            error_str = str(e).lower()
            # Retry on rate limits and server errors
            if any(code in error_str for code in ['429', 'rate_limit', 'rate limit', '503', '502', '500']):
                if attempt < MAX_RETRIES:
                    wait = min(2 ** attempt * 2, 60)
                    print(f"  ⏳ Rate limited (attempt {attempt+1}/{MAX_RETRIES}). Waiting {wait}s...")
                    time.sleep(wait)
                    continue
            # Don't retry on other errors — let the caller handle them
            raise
    
    raise Exception("Max retries exceeded for LLM call")