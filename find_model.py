import urllib.request, json
resp = urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=10)
data = json.loads(resp.read())
for m in data.get("data", []):
    if "4o-mini" in m["id"].lower():
        print(f"{m['id']:55s} {m.get('name','')}")
