# SPECTRA API - Complete Usage Examples

Practical examples for using every SPECTRA API endpoint with cURL, Python, and JavaScript.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Search Operations](#search-operations)
3. [Semantic Analysis](#semantic-analysis)
4. [Channels & Messages](#channels--messages)
5. [User Management](#user-management)
6. [Configuration](#configuration)

---

## Authentication

### Login and Get Tokens

Authenticate user and receive JWT tokens for subsequent requests.

**cURL:**
```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin"
  }'
```

**Python:**
```python
import requests

response = requests.post(
    'http://localhost:5000/api/auth/login',
    json={
        'username': 'admin',
        'password': 'admin'
    }
)

tokens = response.json()
access_token = tokens['access_token']
refresh_token = tokens['refresh_token']
print(f"Access Token: {access_token}")
```

**JavaScript:**
```javascript
fetch('http://localhost:5000/api/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    username: 'admin',
    password: 'admin'
  })
})
.then(r => r.json())
.then(data => {
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
})
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "user_id": "user_001",
    "username": "admin",
    "roles": ["admin"],
    "created_at": "2024-01-01T00:00:00Z"
  }
}
```

---

### Refresh Access Token

Get a new access token using refresh token.

**cURL:**
```bash
curl -X POST http://localhost:5000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**Python:**
```python
response = requests.post(
    'http://localhost:5000/api/auth/refresh',
    json={'refresh_token': refresh_token}
)
new_access_token = response.json()['access_token']
```

---

### Get User Profile

Retrieve authenticated user's profile.

**cURL:**
```bash
curl -X GET http://localhost:5000/api/auth/profile \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Python:**
```python
response = requests.get(
    'http://localhost:5000/api/auth/profile',
    headers={'Authorization': f'Bearer {access_token}'}
)
profile = response.json()
```

---

## Search Operations

### Hybrid Search (Keyword + Semantic)

Search using both full-text and vector similarity.

**cURL:**
```bash
curl -X POST http://localhost:5000/api/search/hybrid \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "suspicious financial activity",
    "limit": 20,
    "offset": 0,
    "search_type": "hybrid",
    "filters": {
      "channel_id": -1001234567890,
      "date_from": "2024-01-01",
      "date_to": "2024-12-31"
    }
  }'
```

**Python:**
```python
import requests

response = requests.post(
    'http://localhost:5000/api/search/hybrid',
    headers={'Authorization': f'Bearer {access_token}'},
    json={
        'query': 'suspicious financial activity',
        'limit': 20,
        'search_type': 'hybrid',
        'filters': {
            'channel_id': -1001234567890,
            'date_from': '2024-01-01',
            'date_to': '2024-12-31'
        }
    }
)

results = response.json()
print(f"Found {results['total']} results in {results['search_time_ms']}ms")

for result in results['results']:
    print(f"  - {result['content'][:50]}... (score: {result['relevance_score']})")
```

**JavaScript:**
```javascript
const searchHybrid = async (query, token) => {
  const response = await fetch('http://localhost:5000/api/search/hybrid', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      query: query,
      limit: 20,
      search_type: 'hybrid'
    })
  });
  return response.json();
};
```

**Response:**
```json
{
  "results": [
    {
      "message_id": 123,
      "channel_id": -1001234567890,
      "user_id": 456,
      "content": "Wire transfer detected from suspicious account...",
      "date": "2024-06-15T10:30:00Z",
      "relevance_score": 0.92,
      "match_type": "hybrid",
      "metadata": {
        "fts5_score": 45.2,
        "vector_score": 0.89
      }
    }
  ],
  "total": 150,
  "search_time_ms": 145
}
```

---

### Pure Semantic Search

Search using only vector similarity (conceptual matching).

**cURL:**
```bash
curl -X POST http://localhost:5000/api/search/semantic \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "unauthorized access attempts",
    "limit": 20,
    "min_score": 0.7
  }'
```

**Python:**
```python
response = requests.post(
    'http://localhost:5000/api/search/semantic',
    headers={'Authorization': f'Bearer {access_token}'},
    json={
        'query': 'unauthorized access attempts',
        'limit': 20,
        'min_score': 0.7
    }
)
```

---

### Pure Full-Text Search

Search using only keyword matching (FTS5).

**cURL:**
```bash
curl -X POST http://localhost:5000/api/search/fulltext \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "malware OR trojan OR ransomware",
    "limit": 50,
    "match_type": "any"
  }'
```

**Python:**
```python
# Supports FTS5 syntax: phrases, boolean, wildcards
response = requests.post(
    'http://localhost:5000/api/search/fulltext',
    headers={'Authorization': f'Bearer {access_token}'},
    json={
        'query': '"data breach" AND (confidential OR classified)',
        'limit': 50
    }
)
```

---

## Semantic Analysis

### Message Clustering

Group messages into topics based on semantic similarity.

**K-Means Clustering:**

**cURL:**
```bash
curl -X POST http://localhost:5000/api/search/clustering \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "kmeans",
    "n_clusters": 10,
    "parameters": {
      "max_iter": 100,
      "random_state": 42
    }
  }'
```

**Python:**
```python
response = requests.post(
    'http://localhost:5000/api/search/clustering',
    headers={'Authorization': f'Bearer {access_token}'},
    json={
        'algorithm': 'kmeans',
        'n_clusters': 10,
        'parameters': {
            'max_iter': 100
        }
    }
)

clustering_results = response.json()
for cluster in clustering_results['clusters']:
    print(f"Cluster {cluster['cluster_id']}: {cluster['label']} ({cluster['size']} messages)")
```

**DBSCAN Clustering:**

**cURL:**
```bash
curl -X POST http://localhost:5000/api/search/clustering \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "dbscan",
    "parameters": {
      "eps": 0.5,
      "min_samples": 5
    }
  }'
```

**Response:**
```json
{
  "clusters": [
    {
      "cluster_id": 0,
      "label": "Financial Fraud Discussion",
      "size": 245,
      "messages": [123, 124, 125, ...],
      "centroid_score": 0.88,
      "temporal_range": ["2024-01-01", "2024-03-15"]
    },
    {
      "cluster_id": 1,
      "label": "Malware Distribution",
      "size": 167,
      "messages": [456, 457, 458, ...],
      "centroid_score": 0.85,
      "temporal_range": ["2024-02-01", "2024-04-20"]
    }
  ],
  "total_clusters": 8,
  "silhouette_score": 0.42
}
```

---

### Anomaly Detection

Identify unusual messages and patterns.

**Isolation Forest:**

**cURL:**
```bash
curl -X POST http://localhost:5000/api/search/anomalies \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "isolation_forest",
    "contamination": 0.1,
    "parameters": {
      "random_state": 42
    }
  }'
```

**Local Outlier Factor:**

**cURL:**
```bash
curl -X POST http://localhost:5000/api/search/anomalies \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "lof",
    "parameters": {
      "n_neighbors": 20,
      "contamination": 0.1
    }
  }'
```

**Python:**
```python
response = requests.post(
    'http://localhost:5000/api/search/anomalies',
    headers={'Authorization': f'Bearer {access_token}'},
    json={
        'algorithm': 'isolation_forest',
        'contamination': 0.1
    }
)

anomalies = response.json()
print(f"Found {anomalies['total_anomalies']} anomalies:")

for anomaly in anomalies['anomalies']:
    print(f"  Score: {anomaly['anomaly_score']:.2f}")
    print(f"  Type: {anomaly['anomaly_type']}")
    print(f"  Reason: {anomaly['reasoning']}")
```

**Response:**
```json
{
  "anomalies": [
    {
      "message_id": 789,
      "content": "Unusual pattern detected in message...",
      "anomaly_score": 0.95,
      "anomaly_type": "isolated_vector",
      "reasoning": "Vector position 5.2 standard deviations from cluster mean"
    },
    {
      "message_id": 790,
      "content": "Another suspicious message...",
      "anomaly_score": 0.87,
      "anomaly_type": "density_outlier",
      "reasoning": "Local outlier factor 0.62 indicates isolation"
    }
  ],
  "total_anomalies": 42,
  "algorithm": "isolation_forest"
}
```

---

### Find Correlations

Find messages related to a specific message.

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/search/123/correlations?type=semantic&limit=20" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Python:**
```python
response = requests.get(
    'http://localhost:5000/api/search/123/correlations',
    headers={'Authorization': f'Bearer {access_token}'},
    params={
        'type': 'semantic',  # semantic, temporal, user, entity
        'limit': 20,
        'min_score': 0.7
    }
)

correlations = response.json()
print(f"Message {correlations['source_message_id']} correlates with:")

for corr in correlations['correlations']:
    print(f"  - Message {corr['target_message_id']}")
    print(f"    Score: {corr['correlation_score']:.2f}")
    print(f"    Type: {corr['relationship_type']}")
```

**Response:**
```json
{
  "source_message_id": 123,
  "correlations": [
    {
      "target_message_id": 456,
      "correlation_score": 0.92,
      "relationship_type": "semantic_similarity",
      "explanation": "Both discuss suspicious account activity"
    },
    {
      "target_message_id": 789,
      "correlation_score": 0.78,
      "relationship_type": "temporal_proximity",
      "explanation": "Occurred within 2 hours"
    }
  ],
  "total_correlations": 15
}
```

---

### Threat Scoring

Calculate risk assessment for a message.

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/search/123/threat-score" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Python:**
```python
response = requests.get(
    'http://localhost:5000/api/search/123/threat-score',
    headers={'Authorization': f'Bearer {access_token}'}
)

threat = response.json()
print(f"Threat Score: {threat['overall_score']:.2f}")
print(f"Risk Level: {threat['risk_level']}")
print("\nFactors:")
for factor, score in threat['factors'].items():
    print(f"  {factor}: {score:.2f}")
print(f"\nReasoning: {threat['reasoning']}")
```

**Response:**
```json
{
  "overall_score": 0.87,
  "risk_level": "critical",
  "factors": {
    "anomaly_score": 0.92,
    "keyword_score": 0.78,
    "behavior_score": 0.85,
    "pattern_score": 0.92
  },
  "reasoning": "Multiple threat indicators detected: unusual vector pattern, threat keywords present, anomalous user behavior, matches known attack signatures"
}
```

---

## Channels & Messages

### List Channels

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/channels?limit=20&offset=0" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Python:**
```python
response = requests.get(
    'http://localhost:5000/api/channels',
    headers={'Authorization': f'Bearer {access_token}'},
    params={'limit': 20}
)

channels = response.json()
for channel in channels['channels']:
    print(f"#{channel['name']} ({channel['message_count']} messages)")
```

---

### Get Channel Details

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/channels/-1001234567890" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

### Get Channel Statistics

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/channels/-1001234567890/stats" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "channel_id": -1001234567890,
  "total_messages": 5000,
  "unique_users": 234,
  "date_range": {
    "first": "2024-01-01",
    "last": "2024-12-15"
  },
  "activity": {
    "messages_per_day": 15.2,
    "peak_hour": 14,
    "peak_day": "Wednesday"
  }
}
```

---

### List Messages

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/messages?channel_id=-1001234567890&limit=50" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

### Get Message Details

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/messages/123" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

### Get Message Context

Get messages before and after a specific message (for conversation threading).

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/messages/123/context?before=5&after=5" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## User Management

### Create User

**cURL:**
```bash
curl -X POST http://localhost:5000/api/admin/users \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "analyst",
    "password": "secure_password",
    "role": "analyst",
    "email": "analyst@example.com"
  }'
```

---

### List Users

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/admin/users" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

### Update User

**cURL:**
```bash
curl -X PUT "http://localhost:5000/api/admin/users/user_002" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "admin",
    "email": "newemail@example.com"
  }'
```

---

### Delete User

**cURL:**
```bash
curl -X DELETE "http://localhost:5000/api/admin/users/user_002" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## Configuration

### Get Search Configuration

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/search/config" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "embedding_model": "all-MiniLM-L6-v2",
  "embedding_dimension": 384,
  "qdrant_url": "http://qdrant:6333",
  "database_path": "spectra.db",
  "fts5_enabled": true,
  "vector_search_enabled": true,
  "clustering_algorithms": ["kmeans", "dbscan"],
  "anomaly_detection_algorithms": ["isolation_forest", "lof"],
  "max_query_length": 500,
  "max_results": 100
}
```

---

### Get Search Statistics

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/search/statistics" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "total_messages": 125000,
  "total_vectors": 125000,
  "fts5_index_size_mb": 45,
  "qdrant_collection_size_mb": 480,
  "last_index_update": "2024-11-25T14:30:00Z",
  "search_performance": {
    "avg_hybrid_search_ms": 145,
    "avg_semantic_search_ms": 95,
    "avg_fulltext_search_ms": 28
  }
}
```

---

### Get System Health

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/admin/health" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-11-25T14:35:00Z",
  "services": {
    "api": "ok",
    "database": "ok",
    "qdrant": "ok"
  },
  "performance": {
    "uptime_hours": 48,
    "requests_total": 5234,
    "requests_per_minute": 12,
    "avg_response_time_ms": 125
  },
  "resources": {
    "memory_used_mb": 512,
    "memory_available_mb": 1024,
    "cpu_usage_percent": 15
  }
}
```

---

### View System Logs

**cURL:**
```bash
curl -X GET "http://localhost:5000/api/admin/logs?limit=100&level=ERROR" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "logs": [
    {
      "timestamp": "2024-11-25T14:30:15Z",
      "level": "ERROR",
      "service": "api",
      "message": "Database connection timeout",
      "details": {...}
    }
  ],
  "total": 42,
  "filtered": 5
}
```

---

## Rate Limiting

All endpoints enforce rate limiting. Check response headers:

```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 28
X-RateLimit-Reset: 1700920200
Retry-After: 60
```

When limit exceeded (HTTP 429):
```json
{
  "error": "Rate limit exceeded",
  "rate_limit": {
    "limit": 30,
    "current": 31,
    "remaining": 0,
    "reset": 1700920200
  }
}
```

---

## Error Handling

### Common Error Responses

**Invalid Request (400):**
```json
{
  "error": "Invalid input: query must be 3-500 characters"
}
```

**Unauthorized (401):**
```json
{
  "error": "Invalid or expired token"
}
```

**Forbidden (403):**
```json
{
  "error": "Insufficient permissions for this operation"
}
```

**Not Found (404):**
```json
{
  "error": "Message not found"
}
```

**Server Error (500):**
```json
{
  "error": "Internal server error"
}
```

---

## Best Practices

1. **Always use HTTPS in production**
2. **Store tokens securely** (localStorage for SPA, httpOnly cookies for traditional apps)
3. **Implement token refresh** before expiry (access tokens valid 1 hour)
4. **Handle rate limiting gracefully** (respect Retry-After header)
5. **Validate input** client-side to reduce invalid requests
6. **Cache results** where appropriate (search results are stable)
7. **Use pagination** for large result sets (offset/limit)
8. **Monitor rate limits** and adjust batch sizes accordingly
9. **Log all errors** for debugging
10. **Test with different user roles** to verify authorization

---

**API Version**: 1.0
**Last Updated**: November 25, 2024
**Status**: Production Ready
