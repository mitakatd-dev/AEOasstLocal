"""
Shared constants used across multiple routers.
"""

# Maps browser/extension-facing platform names to internal LLM identifiers
# stored in the database.
#   "chatgpt"    → the ChatGPT web portal  → stored as "openai"
#   "gemini"     → the Gemini web portal   → stored as "gemini"
#   "perplexity" → the Perplexity portal   → stored as "perplexity"
BROWSER_TO_LLM: dict[str, str] = {
    "chatgpt":    "openai",
    "gemini":     "gemini",
    "perplexity": "perplexity",
}
