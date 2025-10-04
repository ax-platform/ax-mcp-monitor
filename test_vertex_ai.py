#!/usr/bin/env python3

import os
import vertexai
from vertexai.generative_models import GenerativeModel

# Load API key from environment
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print("Error: GEMINI_API_KEY not found in environment")
    exit(1)

print(f"Using API key: {api_key[:10]}...")

try:
    # Initialize Vertex AI with your project
    project_id = "gemini-agents-473418"
    location = "us-central1"

    # Set up authentication using the API key
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = None  # Force API key auth

    print("Initializing Vertex AI...")
    vertexai.init(project=project_id, location=location)

    # Initialize the model
    model = GenerativeModel("gemini-2.0-flash-exp")

    print("Testing Vertex AI Gemini API...")

    # Generate content
    response = model.generate_content("Explain how AI works in a few words")

    print("Response:")
    print(response.text)
    print("\nAPI test successful!")

except Exception as e:
    print(f"Error testing Vertex AI: {e}")
    print(f"Error type: {type(e).__name__}")