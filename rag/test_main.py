from app.main import investigate_incident


incident = """
The payment API is returning 503 errors.
Database connections are exhausted.
Request latency has increased significantly.
"""


result = investigate_incident(incident)


print("\nRETRIEVED INCIDENTS")
print("=" * 60)

for item in result["retrieved_incidents"]:
    print("Source:", item["chunk"].source)
    print("Similarity:", round(item["score"], 3))
    print()


print("\nINVESTIGATION")
print("=" * 60)

print(result["answer"])
