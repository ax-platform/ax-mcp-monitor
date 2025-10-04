#!/usr/bin/env python3

import os
from google import genai
from google.genai.types import HttpOptions

# Load API key from environment
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print("Error: GEMINI_API_KEY not found in environment")
    exit(1)

print(f"Using API key: {api_key[:10]}...")

try:
    # Initialize client
    client = genai.Client(
        api_key=api_key,
        http_options=HttpOptions(api_version="v1")
    )

    print("Testing Gemini API...")

    # Test streaming generation
    response_chunks = []
    for chunk in client.models.generate_content_stream(
        model="gemini-2.5-flash",
        contents="Explain how AI works in a few words",
    ):
        print(chunk.text, end="", flush=True)
        response_chunks.append(chunk.text)

    print("\n\nAPI test successful!")
    print(f"Total response length: {len(''.join(response_chunks))} characters")

except Exception as e:
    print(f"Error testing Gemini API: {e}")
    print(f"Error type: {type(e).__name__}")