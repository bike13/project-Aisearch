import requests
import json

url = "https://api.bochaai.com/v1/web-search"

payload = json.dumps({
  "query": "天空为什么是蓝色的？",
  "summary": True,
  "count": 10,
  "page": 1
})

headers = {
  'Authorization': 'sk-8569e0380e8d4257ab3c0bc43f0a2824',
  'Content-Type': 'application/json'
}

response = requests.post(url, headers=headers, data=payload)

print(response.json())