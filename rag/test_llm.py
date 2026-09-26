from app.llm import LLM


llm = LLM()

prompt = """
You are an AI incident investigation assistant.

Explain what database connection pool exhaustion means
in simple technical terms.
"""

answer = llm.generate(prompt)

print("\nQWEN RESPONSE")
print("=" * 50)
print(answer)
