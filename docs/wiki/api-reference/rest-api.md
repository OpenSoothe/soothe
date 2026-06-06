# REST API Reference

The Soothe daemon provides a comprehensive HTTP REST API for health checks, configuration management, autopilot operations, and system management.

**Base URL**: `http://localhost:8080/api/v1` (configurable)  
**Protocol**: REST over HTTP  
**Format**: JSON request/response  
**Documentation**: Swagger UI at `/docs`, ReDoc at `/redoc`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Health & Status](#health--status)
3. [Configuration](#configuration)
4. [Autopilot Operations](#autopilot-operations)
5. [File Operations](#file-operations)
6. [System Operations](#system-operations)

---

## Authentication

The REST API currently operates in **unauthenticated mode** for local development. Future versions will support:

- API key authentication (`Authorization: Bearer <api_key>`)
- JWT tokens for session-based auth
- OAuth 2.0 for enterprise deployments

---

## Health & Status

### Health Check

**GET** `/api/v1/health`

Check daemon health status with queue metrics.

**Response**:
```json
{
  "status": "healthy",
  "transport": "http_rest",
  "queues": {
    "event_queues": {
      "max_depth": 152,
      "avg_depth": 45.3,
      "clients_near_capacity": 0
    }
  }
}
```

**Status Codes**:
- `200 OK`: Daemon is healthy

**Example**:
```bash
curl http://localhost:8080/api/v1/health
```

---

### Daemon Status

**GET** `/api/v1/status`

Get daemon operational status.

**Response**:
```json
{
  "status": "running",
  "transport": "http_rest",
  "client_count": 3
}
```

**Status Codes**:
- `200 OK`: Status retrieved successfully

**Example**:
```bash
curl http://localhost:8080/api/v1/status
```

---

### Version Information

**GET** `/api/v1/version`

Get daemon version and protocol information.

**Response**:
```json
{
  "version": "1.2.3",
  "protocol": "soothe-rest-v1"
}
```

**Status Codes**:
- `200 OK`: Version information

**Example**:
```bash
curl http://localhost:8080/api/v1/version
```

---

## Configuration

### Get Configuration

**GET** `/api/v1/config`

Retrieve current daemon configuration.

**Response**:
```json
{
  "config": {
    "providers": {
      "openai": {
        "type": "openai",
        "api_key": "***redacted***"
      }
    },
    "models": {
      "default": "openai:gpt-4",
      "planner": "openai:gpt-4o"
    },
    "agent": {
      "max_iterations": 50,
      "parallel_tools": true
    }
  }
}
```

**Status Codes**:
- `200 OK`: Configuration retrieved

**Example**:
```bash
curl http://localhost:8080/api/v1/config
```

---

### Update Configuration

**PUT** `/api/v1/config`

Update daemon configuration.

**Request Body**:
```json
{
  "updates": {
    "agent.max_iterations": 100,
    "protocols.memory.max_items": 200
  }
}
```

**Response**:
```json
{
  "status": "updated",
  "updates": {
    "agent.max_iterations": 100,
    "protocols.memory.max_items": 200
  }
}
```

**Status Codes**:
- `200 OK`: Configuration updated
- `400 Bad Request`: Invalid configuration path
- `500 Internal Server Error`: Update failed

**Example**:
```bash
curl -X PUT http://localhost:8080/api/v1/config \
  -H "Content-Type: application/json" \
  -d '{"updates": {"agent.max_iterations": 100}}'
```

---

### Get Configuration Schema

**GET** `/api/v1/config/schema`

Retrieve the configuration schema for validation.

**Response**:
```json
{
  "schema": {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
      "providers": {
        "type": "object",
        "description": "Model provider configurations"
      },
      "models": {
        "type": "object",
        "description": "Model role routing"
      }
    }
  }
}
```

**Status Codes**:
- `200 OK`: Schema retrieved

**Example**:
```bash
curl http://localhost:8080/api/v1/config/schema
```

---

## Autopilot Operations

All autopilot endpoints return `503 Service Unavailable` if autopilot is not enabled or the service is not initialized.

### Get Autopilot Status

**GET** `/api/v1/autopilot/status`

Get overall autopilot state and loop pool information.

**Response**:
```json
{
  "state": "active",
  "running": true,
  "dreaming": false,
  "loop_pool": {
    "active_loops": 3,
    "idle_loops": 2,
    "max_loops": 10
  }
}
```

**States**:
- `active`: Autopilot is actively processing goals
- `dreaming`: Autopilot is in low-power idle mode (no active goals)

**Status Codes**:
- `200 OK`: Status retrieved
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl http://localhost:8080/api/v1/autopilot/status
```

---

### List Goals

**GET** `/api/v1/autopilot/goals`

List all autopilot goals with their current status.

**Response**:
```json
{
  "goals": [
    {
      "id": "goal-123",
      "description": "Analyze sales data and create report",
      "status": "running",
      "priority": 50,
      "created_at": "2024-01-15T10:30:00Z",
      "workspace": "/home/user/projects/data"
    },
    {
      "id": "goal-456",
      "description": "Update documentation",
      "status": "pending",
      "priority": 30,
      "created_at": "2024-01-15T11:00:00Z"
    }
  ],
  "source": "autopilot_service"
}
```

**Goal Statuses**:
- `pending`: Waiting to be processed
- `running`: Currently being executed
- `completed`: Successfully finished
- `failed`: Execution failed
- `cancelled`: User cancelled
- `needs_confirmation`: Waiting for approval (MUST-confirm)

**Status Codes**:
- `200 OK`: Goals listed
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl http://localhost:8080/api/v1/autopilot/goals
```

---

### Get Goal Details

**GET** `/api/v1/autopilot/goals/{goal_id}`

Get detailed information for a specific goal.

**Path Parameters**:
- `goal_id`: Goal identifier (string)

**Response**:
```json
{
  "goal": {
    "id": "goal-123",
    "description": "Analyze sales data and create report",
    "status": "running",
    "priority": 50,
    "created_at": "2024-01-15T10:30:00Z",
    "started_at": "2024-01-15T10:35:00Z",
    "workspace": "/home/user/projects/data",
    "thread_id": "thread-abc-123",
    "loop_id": "loop-def-456",
    "metadata": {
      "source": "http_api",
      "user_id": "user-001"
    },
    "progress": {
      "steps_completed": 2,
      "steps_total": 5,
      "current_step": "Processing CSV files"
    }
  },
  "source": "autopilot_service"
}
```

**Status Codes**:
- `200 OK`: Goal details retrieved
- `404 Not Found`: Goal not found
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl http://localhost:8080/api/v1/autopilot/goals/goal-123
```

---

### Submit Task

**POST** `/api/v1/autopilot/submit`

Submit a new task/goal to autopilot for autonomous execution.

**Request Body**:
```json
{
  "description": "Analyze the quarterly sales data and create a summary report",
  "priority": 50,
  "workspace": "/home/user/projects/sales-analysis"
}
```

**Fields**:
- `description` (required): Task description/goal statement
- `priority` (optional): Priority level (0-100, default: 50)
- `workspace` (optional): Workspace path for file operations

**Response**:
```json
{
  "status": "submitted",
  "goal_id": "goal-new-789"
}
```

**Status Codes**:
- `200 OK`: Task submitted successfully
- `400 Bad Request`: Missing description or invalid workspace
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl -X POST http://localhost:8080/api/v1/autopilot/submit \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Create a Python script to process CSV data",
    "priority": 70,
    "workspace": "/home/user/projects"
  }'
```

---

### Cancel Goal

**DELETE** `/api/v1/autopilot/goals/{goal_id}`

Cancel a running or pending goal.

**Path Parameters**:
- `goal_id`: Goal identifier (string)

**Response**:
```json
{
  "status": "cancelled",
  "goal_id": "goal-123",
  "new_status": "cancelled"
}
```

**Status Codes**:
- `200 OK`: Goal cancelled successfully
- `404 Not Found`: Goal not found
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl -X DELETE http://localhost:8080/api/v1/autopilot/goals/goal-123
```

---

### Approve Goal

**POST** `/api/v1/autopilot/goals/{goal_id}/approve`

Approve a goal that requires confirmation (MUST-confirm mode).

**Path Parameters**:
- `goal_id`: Goal identifier (string)

**Response**:
```json
{
  "status": "approved",
  "goal_id": "goal-123"
}
```

**Status Codes**:
- `200 OK`: Goal approved
- `404 Not Found`: Goal or confirmation not found
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl -X POST http://localhost:8080/api/v1/autopilot/goals/goal-123/approve
```

---

### Reject Goal

**POST** `/api/v1/autopilot/goals/{goal_id}/reject`

Reject a proposed goal that requires confirmation.

**Path Parameters**:
- `goal_id`: Goal identifier (string)

**Response**:
```json
{
  "status": "rejected",
  "goal_id": "goal-123"
}
```

**Status Codes**:
- `200 OK`: Goal rejected
- `404 Not Found`: Goal or confirmation not found
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl -X POST http://localhost:8080/api/v1/autopilot/goals/goal-123/reject
```

---

### Wake from Dreaming

**POST** `/api/v1/autopilot/wake`

Exit dreaming mode and resume active execution.

**Response**:
```json
{
  "status": "wake_sent"
}
```

**Status Codes**:
- `200 OK`: Wake signal sent
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl -X POST http://localhost:8080/api/v1/autopilot/wake
```

---

### Force Dream Mode

**POST** `/api/v1/autopilot/dream`

Force autopilot into dreaming mode (low-power idle state).

**Response**:
```json
{
  "status": "dream_sent"
}
```

**Status Codes**:
- `200 OK`: Dream signal sent
- `503 Service Unavailable`: Autopilot not available

**Example**:
```bash
curl -X POST http://localhost:8080/api/v1/autopilot/dream
```

---

## File Operations

### Upload File

**POST** `/api/v1/files/upload`

Upload a file to the daemon's temporary storage.

**Request**: multipart/form-data with file attachment

**Response**:
```json
{
  "file_id": "file_001",
  "status": "uploaded"
}
```

**Status Codes**:
- `200 OK`: File uploaded successfully

**Example**:
```bash
curl -X POST http://localhost:8080/api/v1/files/upload \
  -F "file=@/path/to/document.pdf"
```

---

### Download File

**GET** `/api/v1/files/{file_id}`

Download a previously uploaded file.

**Path Parameters**:
- `file_id`: File identifier (string)

**Response**: File content with appropriate Content-Type header

**Status Codes**:
- `200 OK`: File downloaded
- `404 Not Found`: File not found

**Example**:
```bash
curl http://localhost:8080/api/v1/files/file_001 --output downloaded.pdf
```

---

### Delete File

**DELETE** `/api/v1/files/{file_id}`

Delete a previously uploaded file.

**Path Parameters**:
- `file_id`: File identifier (string)

**Response**:
```json
{
  "file_id": "file_001",
  "status": "deleted"
}
```

**Status Codes**:
- `200 OK`: File deleted
- `404 Not Found`: File not found

**Example**:
```bash
curl -X DELETE http://localhost:8080/api/v1/files/file_001
```

---

## System Operations

### Shutdown Daemon

**POST** `/api/v1/system/shutdown`

Request graceful daemon shutdown.

**Response**:
```json
{
  "status": "shutting_down"
}
```

**Status Codes**:
- `200 OK`: Shutdown initiated

**Example**:
```bash
curl -X POST http://localhost:8080/api/v1/system/shutdown
```

---

## Error Responses

All endpoints follow a consistent error response format:

### Standard Error

```json
{
  "detail": "Error message describing the issue"
}
```

### HTTP Status Codes

| Code | Description | Common Causes |
|------|-------------|---------------|
| `200 OK` | Request successful | - |
| `400 Bad Request` | Invalid request data | Missing required fields, invalid workspace path, malformed JSON |
| `404 Not Found` | Resource not found | Goal not found, file not found |
| `503 Service Unavailable` | Service not ready | Autopilot not enabled, daemon still warming |
| `500 Internal Server Error` | Server error | Unexpected exception, configuration error |

---

## CORS Configuration

The REST API supports CORS for cross-origin requests:

**Allowed Origins**: Configurable via `transport.http_rest.cors_origins`  
**Default**: `["*"]` (all origins)

**Example Configuration**:
```yaml
transport:
  http_rest:
    enabled: true
    host: localhost
    port: 8080
    cors_origins:
      - "http://localhost:3000"
      - "https://app.example.com"
```

---

## TLS/SSL Support

The REST API can be configured for HTTPS:

**Configuration**:
```yaml
transport:
  http_rest:
    enabled: true
    tls_enabled: true
    tls_cert: "/path/to/cert.pem"
    tls_key: "/path/to/key.pem"
```

**With TLS enabled**, the base URL becomes: `https://localhost:8080/api/v1`

---

## Rate Limiting

The REST API currently does not implement rate limiting. Future versions will support:

- Request rate limits per client
- Concurrent connection limits
- Request size limits

---

## Request/Response Examples

### Submit and Monitor Task

```bash
# 1. Submit task
RESPONSE=$(curl -s -X POST http://localhost:8080/api/v1/autopilot/submit \
  -H "Content-Type: application/json" \
  -d '{"description": "Generate weekly report", "priority": 70}')

GOAL_ID=$(echo $RESPONSE | jq -r '.goal_id')

# 2. Monitor progress
curl http://localhost:8080/api/v1/autopilot/goals/$GOAL_ID

# 3. Cancel if needed
curl -X DELETE http://localhost:8080/api/v1/autopilot/goals/$GOAL_ID
```

---

### Python Client Example

```python
import aiohttp
import asyncio

async def submit_and_monitor():
    """Submit task and monitor progress."""
    
    base_url = "http://localhost:8080/api/v1"
    
    async with aiohttp.ClientSession() as session:
        # Submit task
        async with session.post(
            f"{base_url}/autopilot/submit",
            json={
                "description": "Analyze CSV data",
                "priority": 50,
                "workspace": "/home/user/data"
            }
        ) as resp:
            result = await resp.json()
            goal_id = result["goal_id"]
            print(f"Submitted goal: {goal_id}")
        
        # Monitor status
        async with session.get(f"{base_url}/autopilot/goals/{goal_id}") as resp:
            goal = await resp.json()
            status = goal["goal"]["status"]
            print(f"Goal status: {status}")
        
        # Cancel if running too long
        if status == "running":
            async with session.delete(f"{base_url}/autopilot/goals/{goal_id}") as resp:
                result = await resp.json()
                print(f"Cancelled: {result['status']}")

asyncio.run(submit_and_monitor())
```

---

## WebSocket vs REST Comparison

| Feature | WebSocket | REST API |
|---------|-----------|----------|
| **Connection** | Persistent bidirectional | Ephemeral request/response |
| **Streaming** | Real-time events | Poll-based monitoring |
| **Use Case** | Interactive queries, TUI | Health checks, batch operations |
| **Stateful** | Yes (maintains session) | No (stateless requests) |
| **Performance** | Lower latency | Higher latency |
| **Scalability** | Limited connections | Highly scalable |

**Recommendations**:
- Use **WebSocket** for interactive applications (CLI, TUI, real-time monitoring)
- Use **REST API** for batch operations, health checks, integration with external systems

---

## OpenAPI Documentation

Interactive API documentation is available:

### Swagger UI

**URL**: `http://localhost:8080/docs`

- Interactive endpoint testing
- Request/response schema visualization
- Parameter validation

### ReDoc

**URL**: `http://localhost:8080/redoc`

- Clean, readable documentation
- Searchable endpoint reference
- Schema examples

---

## See Also

- **[SDK API: WebSocketClient](sdk-api.md#websocket-client)** - WebSocket client for real-time communication
- **[Autopilot Documentation](../autonomous-mode.md)** - Autopilot system overview
- **[Daemon Management](../daemon-management.md)** - Daemon lifecycle management
- **[RFC-222 Autopilot](../../specs/RFC-222-autopilot-engine.md)** - Autopilot specification
- **[RFC-400 REST](../../specs/RFC-400-daemon-communication.md)** - REST protocol specification