#!/usr/bin/env python3

import os
import requests
import json

# Load API key from environment
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print("Error: GEMINI_API_KEY not found in environment")
    exit(1)

print(f"Using API key: {api_key[:10]}...")

try:
    # Vertex AI REST API endpoint
    project_id = "gemini-agents-473418"
    location = "us-central1"
    model = "gemini-2.0-flash-exp"

    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/{model}:generateContent"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    data = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": "Explain how AI works in a few words"
                    }
                ]
            }
        ]
    }

    print("Testing Vertex AI REST API...")
    response = requests.post(url, headers=headers, json=data)

    print(f"Status Code: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        if 'candidates' in result and len(result['candidates']) > 0:
            text = result['candidates'][0]['content']['parts'][0]['text']
            print("Response:")
            print(text)
            print("\nAPI test successful!")
        else:
            print("Unexpected response format:")
            print(json.dumps(result, indent=2))
    else:
        print("Error response:")
        print(response.text)

except Exception as e:
    print(f"Error testing Vertex AI: {e}")
    print(f"Error type: {type(e).__name__}")