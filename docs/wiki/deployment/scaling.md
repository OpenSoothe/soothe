# Scaling Strategies

Guide for scaling Soothe deployments from single-node to large-scale production.

## Scaling Tiers

### Tier 1: Single Node (<50 concurrent threads)

- **Architecture**: Docker Compose, single PostgreSQL instance
- **Limits**: ~50 concurrent threads, ~10 parallel goals
- **Reference**: [Production Setup](production-setup.md)

### Tier 2: Multi-Node (<200 concurrent threads)

- **Architecture**: Load balancer + multiple daemon nodes + PostgreSQL replicas
- **Limits**: ~200 concurrent threads, ~30 parallel goals
- **See below**: Multi-node scaling section

### Tier 3: Large Scale (<1000 concurrent threads)

- **Architecture**: Kubernetes + PostgreSQL cluster + Redis coordination
- **Limits**: ~1000 concurrent threads, ~100 parallel goals
- **See below**: Kubernetes scaling section

## Horizontal Scaling: Multi-Node Deployment

### Architecture

```
┌──────────────┐
│ Load Balancer│ (nginx/HAProxy)
└──────┬───────┘
       │ Round-robin routing
       ├─→ ┌──────────────┐
       │   │ Soothe Node 1│
       │   └──────┬───────┘
       │          │ PostgreSQL primary
       ├─→ ┌──────────────┐
       │   │ Soothe Node 2│
       │   └──────┬───────┘
       │          │
       └─────→ ┌──────────────┐
               │ PostgreSQL   │
               │ Primary +    │
               │ Replicas     │
               └──────────────┘
```

### Load Balancer Configuration (nginx)

**Upstream configuration**:
```nginx
upstream soothe_daemons {
    least_conn;  # Route to least busy node
    server soothe-node1:8765 weight=1;
    server soothe-node2:8765 weight=1;
    server soothe-node3:8765 weight=1;
    
    health_check interval=10s fails=3 passes=2;
}

server {
    listen 443 ssl;
    location /ws {
        proxy_pass http://soothe_daemons;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### PostgreSQL Scaling

**Primary-replica setup**:

```yaml
# docker-compose.yml (PostgreSQL cluster)
services:
  postgres-primary:
    image: pgvector:pg17
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    command: ["postgres", "-c", "max_connections=300"]
    
  postgres-replica1:
    image: pgvector:pg17
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    command: |
      postgres
      -c primary_conninfo='host=postgres-primary port=5432 user=postgres password=${POSTGRES_PASSWORD}'
      -c standby_mode=on
```

**Connection pooling**:
```yaml
persistence:
  postgres_pool_min_size: 16
  checkpointer_pool_size: 48
  agentloop_pool_size: 48
```

### Daemon Node Configuration

Each node needs unique workspace mounts:

```yaml
# Node 1: workspace mapping
workspace_mount:
  host_root: /mnt/shared/workspace
  container_root: /var/lib/soothe/workspaces

# Node 2: same shared workspace
workspace_mount:
  host_root: /mnt/shared/workspace
  container_root: /var/lib/soothe/workspaces
```

**Concurrency tuning**:
```yaml
agent:
  autonomous:
    max_parallel_goals: 10  # Per-node limit
    max_loops: 8            # Worker pool size
    
  loop:
    limits:
      max_parallel_tools: 30
      llm_concurrent_limit: 20
```

## Kubernetes Deployment

### Namespace and Secrets

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: soothe-production
---
apiVersion: v1
kind: Secret
metadata:
  name: soothe-secrets
  namespace: soothe-production
type: Opaque
data:
  dashscope-api-key: <base64>
  postgres-password: <base64>
```

### PostgreSQL StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: soothe-postgres
  namespace: soothe-production
spec:
  serviceName: soothe-postgres
  replicas: 3  # Primary + 2 replicas
  selector:
    matchLabels:
      app: soothe-postgres
  template:
    metadata:
      labels:
        app: soothe-postgres
    spec:
      containers:
      - name: postgres
        image: pgvector:pg17
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: soothe-secrets
              key: postgres-password
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: postgres-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

### Soothe Daemon Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: soothe-daemon
  namespace: soothe-production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: soothe-daemon
  template:
    metadata:
      labels:
        app: soothe-daemon
    spec:
      containers:
      - name: soothed
        image: soothed:latest
        env:
        - name: DASHSCOPE_API_KEY
          valueFrom:
            secretKeyRef:
              name: soothe-secrets
              key: dashscope-api-key
        - name: SOOTHE_POSTGRES_BASE_DSN
          value: "postgresql://postgres:$(POSTGRES_PASSWORD)@soothe-postgres-0:5432"
        ports:
        - containerPort: 8765
        volumeMounts:
        - name: workspace
          mountPath: /var/lib/soothe/workspaces
        - name: config
          mountPath: /var/lib/soothe/config
      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: workspace-pvc
      - name: config
        configMap:
          name: soothe-config
```

### Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: soothe-daemon-hpa
  namespace: soothe-production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: soothe-daemon
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Service and Ingress

```yaml
apiVersion: v1
kind: Service
metadata:
  name: soothe-daemon-service
  namespace: soothe-production
spec:
  selector:
    app: soothe-daemon
  ports:
  - port: 8765
    targetPort: 8765
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: soothe-ingress
  namespace: soothe-production
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  tls:
  - hosts:
    - soothe.your-domain.com
    secretName: soothe-tls
  rules:
  - host: soothe.your-domain.com
    http:
      paths:
      - path: /ws
        pathType: Prefix
        backend:
          service:
            name: soothe-daemon-service
            port:
              number: 8765
```

## Performance Tuning

### PostgreSQL Optimization

```sql
-- PostgreSQL configuration
ALTER SYSTEM SET max_connections = 300;
ALTER SYSTEM SET shared_buffers = '1GB';
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET effective_cache_size = '3GB';
ALTER SYSTEM SET random_page_cost = 1.1;  -- For SSDs
ALTER SYSTEM SET effective_io_concurrency = 200;
```

**pgvector optimization**:
```sql
-- HNSW index for fast vector search
CREATE INDEX ON soothe_embeddings USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- IVFFlat for larger datasets
CREATE INDEX ON soothe_embeddings USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### Daemon Pool Sizing

```yaml
persistence:
  postgres_pool_min_size: 16  # Base pool
  checkpointer_pool_size: 48  # LangGraph checkpoints
  agentloop_pool_size: 48     # StrangeLoop state
  
agent:
  autonomous:
    max_loops: 8              # Worker pool per node
    max_parallel_goals: 10    # Concurrent goal execution
    
  loop:
    limits:
      max_parallel_tools: 30  # Tool call parallelism
      llm_concurrent_limit: 20 # LLM API concurrency
      llm_rpm_limit: 500      # Requests per minute
```

**Pool sizing formula**:
- `postgres_pool_min_size`: 4 × number of nodes
- `checkpointer_pool_size`: 24 × number of nodes
- `max_loops`: CPU cores × 2
- `max_parallel_goals`: max_loops ÷ 2

### LLM Rate Limiting

**Provider-specific limits**:

```yaml
agent:
  loop:
    limits:
      llm_rpm_limit: 500       # OpenAI limit
      llm_concurrent_limit: 20 # Max concurrent API calls
      
      # Adaptive timeouts for rate limit handling
      llm_call_timeout_seconds: 120
      llm_call_timeout_adaptive: true
      llm_retry_on_timeout: true
      llm_max_timeout_retries: 3
```

**Provider rate limits** (reference):
- OpenAI: 500 RPM (Tier 1), 5000 RPM (Tier 2)
- Anthropic: 1000 RPM default
- DashScope: 60 RPM (free), 600 RPM (paid)

## Capacity Planning

### Thread Capacity Estimation

**Formula**: Max concurrent threads = max_loops × max_parallel_goals × nodes

**Example**:
- 3 nodes × 8 loops × 10 parallel goals = 240 concurrent threads

**Database capacity**:
- PostgreSQL: 300 max_connections recommended
- Each thread: 2-3 database connections (checkpointer + metadata)

### Memory Estimation

**Per-thread memory**: ~50 MB (StrangeLoop state + LLM context)

**Total memory**: Threads × 50 MB + Base daemon memory

**Example**:
- 100 threads × 50 MB = 5 GB
- Base daemon: 500 MB
- Total: 5.5 GB per node

**Recommendation**: 8 GB RAM per node for 100 threads

### CPU Estimation

**Per-thread CPU**: 0.5-1.0 cores (LLM reasoning)

**Total CPU**: Threads × 0.5 cores

**Example**:
- 100 threads × 0.5 cores = 50 cores total
- 3 nodes: 17 cores per node

**Recommendation**: 8-16 cores per node

### Storage Estimation

**Thread storage**: ~1-5 MB per thread (checkpoints + metadata)

**Vector storage**: Embedding size × vectors

**Example** (1000 threads, 1 year retention):
- Threads: 1000 × 5 MB = 5 GB
- Checkpoints: 1000 × 10 MB = 10 GB
- Vectors: 100K vectors × 1536 dims × 4 bytes = 600 MB

**Recommendation**: 100 GB PostgreSQL storage, expandable

## Scaling Triggers

### When to Scale Up

**Indicators**:
- CPU utilization > 70% sustained
- Memory utilization > 80%
- PostgreSQL connection pool exhausted
- Thread queue depth > 20
- LLM rate limit errors frequent

**Actions**:
1. Add daemon nodes (+1-2)
2. Increase PostgreSQL replicas
3. Tune pool sizes
4. Optimize queries

### When to Scale Down

**Indicators**:
- CPU utilization < 30% sustained
- Memory utilization < 40%
- Thread queue depth < 5
- Low concurrent thread count

**Actions**:
1. Remove daemon nodes (-1)
2. Reduce pool sizes
3. Consolidate PostgreSQL replicas

## Related Documentation

- [Production Setup](production-setup.md) - Single-node deployment
- [Monitoring Guide](monitoring.md) - Performance monitoring
- [Security Hardening](security.md) - Secure scaling
- [Backup Recovery](backup-recovery.md) - Database backup strategies

---

**Need scaling help?** See [Troubleshooting](../troubleshooting.md) or calculate capacity with formulas above.