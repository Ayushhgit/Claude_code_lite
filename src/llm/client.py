import os
from dotenv import load_dotenv
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

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

def _is_rate_limit_error(exception):
    error_str = str(exception).lower()
    return any(code in error_str for code in ['429', 'rate_limit', 'rate limit', '503', '502', '500'])

@retry(
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(6),
    retry=retry_if_exception(_is_rate_limit_error),
    reraise=True
)
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

@retry(
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(6),
    retry=retry_if_exception(_is_rate_limit_error),
    reraise=True
)
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
