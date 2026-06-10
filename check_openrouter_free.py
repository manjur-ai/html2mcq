"""List all free vision-capable models on OpenRouter."""
import urllib.request, json
from html2mcq.generator import _parse_operator_model

resp = urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=15)
data = json.loads(resp.read())

free_vision = []
for m in data.get("data", []):
    mid = m["id"]
    pricing = m.get("pricing", {})
    # Check if free (prompt or completion cost is 0)
    is_free = any(
        v is not None and float(v) == 0
        for k, v in pricing.items()
        if v is not None
    )
    if not is_free:
        continue
    # Check if vision-capable: look at architectures, modalities, description
    desc = (m.get("description") or "").lower()
    name = (m.get("name") or "").lower()
    is_vision = any(
        kw in desc or kw in name
        for kw in ["vision", "image", "multimodal", "vlm", "visual"]
    )
    if not is_vision:
        # also check if any endpoint supports image_url
        endpoints = m.get("endpoints", [])
        continues = any("image" in e.get("features", []) for e in endpoints if isinstance(e, dict))
        if not continues:
            continue

    free_vision.append({
        "id": mid,
        "name": m.get("name", ""),
        "pricing": pricing,
        "description": desc[:120],
    })

print(f"Found {len(free_vision)} free vision-capable models on OpenRouter:\n")
for fv in sorted(free_vision, key=lambda x: x["id"]):
    print(f"  {fv['id']}")
    print(f"      {fv['name']}")
    print(f"      pricing: {fv['pricing']}")
    print()
