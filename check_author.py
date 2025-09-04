import requests
import json

# Check if author 1273 exists by searching in a range
response = requests.get('http://localhost:8000/dashboard/authors/search', params={'limit': 10})
data = response.json()
authors = data.get('results', [])

print('Sample authors:')
for author in authors[:5]:
    print(f'ID: {author.get("id")}, Name: {author.get("author_name_en")}, Email: {author.get("email")}, Homepage: {author.get("homepage")}')

# Try to find authors around ID 1273
print('\nSearching for authors with IDs around 1273...')
for test_id in range(1270, 1280):
    try:
        response = requests.get(f'http://localhost:8000/dashboard/authors/{test_id}')
        if response.status_code == 200:
            author_data = response.json()
            print(f'Found author {test_id}: {author_data.get("author_name_en")}, Email: {author_data.get("email")}, Homepage: {author_data.get("homepage")}')
    except:
        pass