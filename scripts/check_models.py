import os, time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(timeout=30000),  # 30 seconds, in milliseconds
)

fill_tool = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="fill_field",
    description="Fill a form field using a reference to a verified profile value.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "element_id": types.Schema(type="INTEGER"),
            "value_ref": types.Schema(type="STRING"),
        },
        required=["element_id", "value_ref"],
    ),
)])

prompt = (
    "Form elements: [1] textbox 'Full name' (empty), [2] textbox 'Date of birth' (empty), "
    "[3] button 'Next'. Available value refs: profile.name, profile.dob. "
    "Fill the date of birth field."
)

candidates = [
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]

for m in candidates:
    print(f"testing {m}...", flush=True)
    start = time.time()
    try:
        r = client.models.generate_content(
            model=m, contents=prompt,
            config=types.GenerateContentConfig(tools=[fill_tool]),
        )
        took = round(time.time() - start, 2)
        calls = r.function_calls
        if calls:
            print(f"  {took}s  {calls[0].name}{dict(calls[0].args)}")
        else:
            print(f"  {took}s  NO TOOL CALL: {(r.text or '')[:60]}")
    except Exception as e:
        took = round(time.time() - start, 2)
        print(f"  {took}s  ERROR: {str(e)[:120]}")
