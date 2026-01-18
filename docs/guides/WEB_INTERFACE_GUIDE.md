# SPECTRA Web Interface & REST API Guide
## Complete Documentation for Web-Based Intelligence Platform

---

## Quick Start

### Running the Web Server

#### Option 1: Direct Python
```bash
# Install dependencies
pip install -r requirements.txt

# Set configuration
export SPECTRA_JWT_SECRET="your-secret-key-here"
export SPECTRA_DEBUG=false

# Run web server
python -m tgarchive.web --host 0.0.0.0 --port 5000
```

#### Option 2: Docker (Recommended)
```bash
# Build image
docker build -t spectra:latest .

# Run container
docker run -d \
  -p 5000:5000 \
  -e SPECTRA_JWT_SECRET="your-secret-key" \
  -v spectra-data:/app/data \
  spectra:latest
```

#### Option 3: Docker Compose
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f spectra

# Stop services
docker-compose down
```

### Access the Dashboard
- **URL**: http://localhost:5000
- **Login**:
  - Username: `admin`
  - Password: `admin`

---

## REST API Overview

### Authentication

All API endpoints (except `/health`) require JWT authentication.

#### Login
```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin"
  }'
```

**Response**:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "user_id": "user_001",
    "username": "admin",
    "roles": ["admin"],
    "created_at": "2024-01-01T00:00:00Z"
  }
}
```

#### Using Access Token
```bash
curl http://localhost:5000/api/channels \
  -H "Authorization: Bearer <access_token>"
```

#### Refresh Token
```bash
curl -X POST http://localhost:5000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token>"}'
```

---

## API Endpoints

### Authentication
- `POST /api/auth/login` - Login
- `POST /api/auth/refresh` - Refresh token
- `POST /api/auth/logout` - Logout
- `GET /api/auth/profile` - Get user profile
- `PUT /api/auth/profile` - Update user profile

### Channels
- `GET /api/channels` - List all channels
- `GET /api/channels/<channel_id>` - Get channel details
- `POST /api/channels` - Add new channel
- `DELETE /api/channels/<channel_id>` - Remove channel
- `GET /api/channels/<channel_id>/statistics` - Get channel stats

### Messages
- `GET /api/messages/<channel_id>` - Get messages from channel
- `GET /api/messages/<channel_id>/<message_id>` - Get specific message
- `GET /api/messages/<channel_id>/<message_id>/details` - Get message analysis

### Search
- `POST /api/search` - Full-text search
- `POST /api/search/advanced` - Advanced search with filters
- `POST /api/search/correlation` - Correlation analysis
- `GET /api/search/saved` - Get saved searches
- `POST /api/search/saved` - Save search

### Export
- `POST /api/export` - Create export job
- `GET /api/export/<export_id>` - Get export status
- `GET /api/export/<export_id>/download` - Download export
- `DELETE /api/export/<export_id>` - Cancel export
- `GET /api/export` - List exports
- `GET /api/export/templates` - Get export templates

### Admin
- `GET /api/admin/users` - List users
- `GET /api/admin/users/<user_id>` - Get user details
- `POST /api/admin/users` - Create user
- `PUT /api/admin/users/<user_id>` - Update user
- `DELETE /api/admin/users/<user_id>` - Delete user
- `GET /api/admin/logs` - Get audit logs
- `GET /api/admin/system/health` - System health
- `GET /api/admin/system/config` - System config
- `GET /api/admin/operations` - List operations
- `GET /api/admin/stats` - Get statistics

---

## Search Functionality

### Full-Text Search
```bash
curl -X POST http://localhost:5000/api/search \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "suspicious activity",
    "type": "message",
    "channels": [-1001234567890],
    "date_from": "2024-01-01",
    "date_to": "2024-12-31",
    "limit": 20
  }'
```

### Advanced Search with Filters
```bash
curl -X POST http://localhost:5000/api/search/advanced \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "target",
    "filters": {
      "channels": [-1001234567890, -1001234567891],
      "date_range": {"from": "2024-01-01", "to": "2024-12-31"},
      "sender_ids": [123456789],
      "message_type": ["text", "media"],
      "has_reactions": true
    },
    "aggregations": ["by_date", "by_sender", "by_channel"],
    "limit": 100
  }'
```

### Correlation Search
```bash
curl -X POST http://localhost:5000/api/search/correlation \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "entities": ["user1", "user2", "user3"],
    "time_window": 7,
    "relationship_types": ["mentions", "replies", "forwards", "same_group"]
  }'
```

---

## Export Functionality

### Create Export Job
```bash
curl -X POST http://localhost:5000/api/export \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "channels": [-1001234567890],
    "format": "json",
    "include_media": true,
    "date_range": {
      "from": "2024-01-01",
      "to": "2024-12-31"
    }
  }'
```

**Supported Formats**:
- `json` - Structured JSON format
- `csv` - Comma-separated values
- `xlsx` - Excel spreadsheet
- `pdf` - PDF report with analysis

### Monitor Export Progress
```bash
curl http://localhost:5000/api/export/exp_001 \
  -H "Authorization: Bearer <token>"
```

**Response**:
```json
{
  "export_id": "exp_001",
  "status": "in_progress",
  "progress": 45,
  "total_items": 1000,
  "processed_items": 450,
  "estimated_time_remaining": 150,
  "created_at": "2024-01-15T10:00:00Z"
}
```

---

## Web Dashboard Features

### Dashboard Overview
- **Real-time Metrics**: Active channels, messages, operations
- **System Health**: Database status, API availability
- **Quick Actions**: Start archiving, run search, create export

### Intelligence View
- **Network Graph**: Visualize channel/user relationships
- **Message Timeline**: Chronological view of messages
- **Entity Analysis**: Identified users, locations, keywords
- **Sentiment Analysis**: Message tone and intent

### Search Interface
- **Basic Search**: Simple keyword search
- **Advanced Filters**: Date range, sender, message type
- **Saved Searches**: Store and reuse search patterns
- **Search History**: View previous searches

### Export Center
- **Template Selection**: Choose export format and fields
- **Progress Tracking**: Real-time export progress
- **Batch Operations**: Export multiple channels at once
- **Download Management**: View all exports and redownload

### Admin Panel
- **User Management**: Create, edit, disable users
- **Role Assignment**: Set user roles and permissions
- **Audit Logs**: View all system activities
- **System Configuration**: Manage settings
- **Operation Management**: View and manage running operations

---

## Rate Limiting & Quota Management

### Rate Limits by Endpoint
```
/api/auth/login:           5 requests / 15 minutes (per IP)
/api/channels:             50 requests / minute (per user)
/api/search:               30 requests / minute (per user)
/api/search/correlation:   20 requests / minute (per user)
/api/export:               10 requests / day (per user)
/api/admin/*:              50 requests / minute (admin only)
```

### Rate Limit Headers
All responses include:
```
X-RateLimit-Limit:     100
X-RateLimit-Remaining: 95
X-RateLimit-Reset:     1705334400
```

### Handling Rate Limit Errors
```
Status: 429 Too Many Requests
Retry-After: 60

{
  "error": "Rate limit exceeded",
  "rate_limit": {
    "limit": 30,
    "current": 30,
    "remaining": 0,
    "reset": 1705334400
  }
}
```

---

## Security Headers & Protection

### Implemented Headers
- `Content-Security-Policy`: XSS prevention
- `X-Frame-Options: DENY`: Clickjacking protection
- `X-Content-Type-Options: nosniff`: MIME sniffing prevention
- `Strict-Transport-Security`: HTTPS enforcement
- `Referrer-Policy: strict-origin-when-cross-origin`: Privacy
- `Permissions-Policy`: Block dangerous features

### HTTPS Configuration
```bash
# Generate self-signed cert for testing
openssl req -x509 -newkey rsa:4096 -nodes \
  -out cert.pem -keyout key.pem -days 365

# Run with HTTPS
python -m tgarchive.web --ssl --cert cert.pem --key key.pem
```

---

## Integration Examples

### Python Client Library
```python
import requests
from requests.auth import HTTPBearerAuth

# Login
response = requests.post(
    'http://localhost:5000/api/auth/login',
    json={'username': 'admin', 'password': 'admin'}
)
token = response.json()['access_token']

# Search messages
headers = {'Authorization': f'Bearer {token}'}
response = requests.post(
    'http://localhost:5000/api/search',
    headers=headers,
    json={
        'query': 'target',
        'type': 'message',
        'limit': 20
    }
)
results = response.json()
```

### JavaScript/Node.js Client
```javascript
// Login
const loginResp = await fetch('/api/auth/login', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({username: 'admin', password: 'admin'})
});
const {access_token} = await loginResp.json();

// Search
const searchResp = await fetch('/api/search', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${access_token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({query: 'target', limit: 20})
});
const results = await searchResp.json();
```

### cURL Examples
See API section above for detailed examples.

---

## Troubleshooting

### Common Issues

#### "Invalid authorization header"
- Check token format: `Bearer <token>`
- Ensure token is not expired
- Regenerate using /api/auth/refresh

#### "Rate limit exceeded"
- Wait for reset time shown in header
- Implement exponential backoff
- Use batch operations where possible

#### "Database locked"
- Close other connections
- Wait for current operation to complete
- Check system resources

#### "CORS error"
- Configure SPECTRA_CORS_ORIGINS environment variable
- Add your domain to allowed origins
- Ensure HTTPS in production

---

## Performance Tuning

### Database Optimization
```sql
-- Create indexes for common queries
CREATE INDEX idx_messages_channel ON messages(channel_id);
CREATE INDEX idx_messages_date ON messages(date);
CREATE INDEX idx_messages_sender ON messages(sender_id);

-- Full-text search index
CREATE VIRTUAL TABLE messages_fts USING fts5(text);
```

### Caching Strategy
- Cache channel metadata (1 hour)
- Cache user permissions (15 minutes)
- Cache search results (5 minutes)
- Invalidate on updates

### Connection Pooling
```python
# SQLAlchemy configuration
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}
```

---

## Production Deployment Checklist

- [ ] Change JWT secret to random value (32+ chars)
- [ ] Enable HTTPS with valid certificate
- [ ] Configure correct CORS origins
- [ ] Set DEBUG=false
- [ ] Enable database encryption
- [ ] Set up backup procedure
- [ ] Configure log rotation
- [ ] Set up monitoring/alerting
- [ ] Test SSL/TLS configuration
- [ ] Configure reverse proxy (Nginx)
- [ ] Set resource limits
- [ ] Enable WAF rules
- [ ] Test disaster recovery
- [ ] Create admin user account
- [ ] Set strong admin password
- [ ] Enable audit logging

---

## Support & Documentation

- **API Documentation**: `/api/docs`
- **Security Guide**: `SECURITY_CSNA_2_0.md`
- **Project README**: `README.md`
- **Issues & Bugs**: GitHub Issues

---

**Last Updated**: 2024-11-25
**Version**: 1.0.0
**Status**: ACTIVE
