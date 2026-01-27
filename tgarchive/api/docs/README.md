# SPECTRA API Documentation

## Overview

SPECTRA provides comprehensive programmatic access through four API types:

1. **REST API** - Standard CRUD operations
2. **WebSocket API** - Real-time updates
3. **GraphQL API** - Flexible queries
4. **CLI API** - Command execution via HTTP

## REST API

### Base URL
- Development: `http://localhost:5000/api`
- Production: `https://api.spectra.example.com/api`

### Authentication
All endpoints require JWT authentication via Bearer token:
```
Authorization: Bearer <token>
```

### Endpoints

#### Core Operations
- `POST /api/core/archive` - Archive channel/group
- `GET /api/core/archive/<entity_id>/status` - Get archive status
- `POST /api/core/discover` - Discover groups from seed
- `GET /api/core/discover/<discovery_id>/status` - Get discovery status
- `POST /api/core/network/analyze` - Analyze network graph

#### Accounts
- `GET /api/accounts` - List all accounts
- `POST /api/accounts` - Add new account
- `GET /api/accounts/<account_id>` - Get account details
- `POST /api/accounts/<account_id>/test` - Test account connectivity

#### Forwarding
- `POST /api/forwarding/messages` - Forward messages
- `POST /api/forwarding/all-dialogs` - Forward all dialogs
- `POST /api/forwarding/total-mode` - Total forward mode
- `GET /api/forwarding/schedules` - List forwarding schedules

#### Threat Intelligence
- `POST /api/threat/attribution/analyze` - Analyze writing style
- `POST /api/threat/temporal/analyze` - Analyze temporal patterns
- `POST /api/threat/scoring/calculate` - Calculate threat scores

#### Analytics
- `POST /api/analytics/forecast` - Generate forecasts
- `POST /api/analytics/time-series` - Time series analysis

#### ML/AI
- `POST /api/ml/patterns/detect` - Detect patterns
- `POST /api/ml/semantic/search` - Semantic search

#### Crypto
- `POST /api/crypto/kem/generate` - Generate KEM keypair
- `POST /api/crypto/encrypt` - Encrypt data
- `GET /api/crypto/algorithms` - Get algorithm info

#### Database
- `GET /api/database/channels` - List channels
- `GET /api/database/messages` - Query messages
- `GET /api/database/stats` - Get database statistics

#### OSINT
- `POST /api/osint/targets` - Add target
- `GET /api/osint/targets` - List targets
- `POST /api/osint/scan` - Scan channel for target

#### Services
- `GET /api/services/scheduler/jobs` - List scheduled jobs
- `POST /api/services/scheduler/jobs` - Create scheduled job
- `POST /api/services/mirror` - Mirror group

#### CLI
- `POST /api/cli/execute` - Execute CLI command
- `GET /api/cli/commands` - List available commands
- `GET /api/cli/<command_id>/status` - Get command status

## WebSocket API

### Connection
```
ws://localhost:5000/api/ws
```

### Events

#### Archive Events
- `archive:start` - Archive operation started
- `archive:progress` - Archive progress update
- `archive:complete` - Archive completed

#### Discovery Events
- `discover:start` - Discovery started
- `discover:found` - New group discovered
- `discover:complete` - Discovery completed

#### System Events
- `system:status` - System status update
- `system:metric` - System metric update

### Subscriptions
```javascript
socket.emit('subscribe', { room: 'archive:entity_id' });
socket.on('archive:progress', (data) => {
  console.log('Progress:', data.progress);
});
```

## GraphQL API

### Endpoint
```
POST /api/graphql
GET /api/graphql  # Playground (debug mode)
```

### Example Query
```graphql
query {
  channels(limit: 10) {
    channelId
    title
    archivedMessages
  }
}
```

### Example Mutation
```graphql
mutation {
  archiveChannel(entityId: "@channel_name") {
    taskId
    status
  }
}
```

## CLI API

### Execute Command
```bash
curl -X POST http://localhost:5000/api/cli/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "archive",
    "args": ["--entity", "@channel_name"]
  }'
```

## Rate Limiting

Rate limits are applied per endpoint:
- Standard endpoints: 50 requests/minute
- Heavy operations: 10 requests/minute
- Admin endpoints: 5 requests/minute

Rate limit headers:
- `X-RateLimit-Limit`: Maximum requests
- `X-RateLimit-Remaining`: Remaining requests
- `X-RateLimit-Reset`: Reset timestamp

## Error Handling

All errors follow this format:
```json
{
  "error": "Error type",
  "message": "Human-readable error message"
}
```

Common status codes:
- `400` - Bad Request
- `401` - Unauthorized
- `403` - Forbidden
- `404` - Not Found
- `429` - Rate Limit Exceeded
- `500` - Internal Server Error

## OpenAPI Specification

Full OpenAPI 3.0 specification available at:
- `/api/docs/openapi.yaml`

## GraphQL Schema

GraphQL schema available at:
- `/api/docs/graphql_schema.graphql`
