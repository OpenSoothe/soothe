---
title: "Backup and Recovery"
parent: Deployment
grand_parent: Wiki
nav_order: 5
description: >-
  Comprehensive disaster recovery strategy for Soothe production deployments, covering PostgreSQL backup and recovery.
---

# Backup and Recovery Guide

Comprehensive disaster recovery strategy for Soothe production deployments.

## Overview

Soothe's data consists of:
1. **PostgreSQL databases**: Thread checkpoints, metadata, vectors, memory
2. **Configuration files**: config.yml, .env, secrets
3. **Workspace data**: User project files (managed separately)
4. **Log files**: Daemon logs, thread logs (optional backup)

## Backup Strategy

### Backup Types

| Type | Frequency | Retention | Data |
|------|-----------|-----------|------|
| Full | Weekly | 4 weeks | All PostgreSQL databases + config |
| Incremental | Daily | 7 days | Thread checkpoints + metadata |
| Continuous | Real-time | 24 hours | WAL streaming (PostgreSQL) |
| Configuration | On change | Indefinite | config.yml, secrets |

### Backup Locations

**Local backup**: `/var/backups/soothe/`
**Remote backup**: S3/GCS/Azure Blob storage
**Disaster recovery**: Separate region/zone

## PostgreSQL Backup

### Method 1: pg_dump (Recommended for <50GB)

**Full backup script**:

```bash
#!/bin/bash
# backup-postgres.sh - Weekly full backup

BACKUP_DIR="/var/backups/soothe"
DATE=$(date +%Y%m%d)
POSTGRES_HOST="localhost"
POSTGRES_USER="postgres"

# Create backup directory
mkdir -p ${BACKUP_DIR}/${DATE}

# Backup each database (RFC-802 multi-database)
for db in soothe_checkpoints soothe_metadata soothe_vectors soothe_memory; do
    pg_dump -h ${POSTGRES_HOST} -U ${POSTGRES_USER} -d ${db} \
        --format=custom \
        --file=${BACKUP_DIR}/${DATE}/${db}.dump
done

# Backup config files
cp /var/lib/soothe/config/config.yml ${BACKUP_DIR}/${DATE}/
cp /var/lib/soothe/.env ${BACKUP_DIR}/${DATE}/

# Compress backup
tar czf ${BACKUP_DIR}/soothe_backup_${DATE}.tar.gz ${BACKUP_DIR}/${DATE}

# Remove uncompressed files
rm -rf ${BACKUP_DIR}/${DATE}

# Upload to remote storage (S3 example)
aws s3 cp ${BACKUP_DIR}/soothe_backup_${DATE}.tar.gz \
    s3://soothe-backups/${DATE}/

# Cleanup old backups (keep 4 weeks)
find ${BACKUP_DIR} -name "soothe_backup_*.tar.gz" -mtime +28 -delete
```

**Incremental backup script**:

```bash
#!/bin/bash
# backup-incremental.sh - Daily incremental backup

BACKUP_DIR="/var/backups/soothe"
DATE=$(date +%Y%m%d)

# Backup only thread-related tables (checkpoints + metadata)
pg_dump -h localhost -U postgres -d soothe_checkpoints \
    --table='checkpoints' --table='checkpoint_blobs' \
    --format=custom \
    --file=${BACKUP_DIR}/incremental_checkpoints_${DATE}.dump

pg_dump -h localhost -U postgres -d soothe_metadata \
    --table='threads' --table='goals' \
    --format=custom \
    --file=${BACKUP_DIR}/incremental_metadata_${DATE}.dump

# Upload to S3
aws s3 sync ${BACKUP_DIR}/ s3://soothe-backups/incremental/ \
    --exclude "*" --include "incremental_*_${DATE}.dump"
```

### Method 2: WAL Streaming (Continuous Backup)

**PostgreSQL WAL configuration**:

```sql
-- Enable WAL archiving
ALTER SYSTEM SET wal_level = replica;
ALTER SYSTEM SET archive_mode = on;
ALTER SYSTEM SET archive_command = 
    'aws s3 cp %p s3://soothe-backups/wal/%f';

-- Enable replication slots
SELECT pg_create_physical_replication_slot('soothe_backup_slot');
```

**WAL receiver script**:

```bash
#!/bin/bash
# wal-receiver.sh - Continuous WAL streaming

pg_receivewal \
    --host=localhost \
    --port=5432 \
    --username=postgres \
    --slot=soothe_backup_slot \
    --directory=/var/backups/soothe/wal \
    --compress=9 \
    --verbose
```

**Restore from WAL**:
```bash
# Point-in-time recovery (PITR)
pg_basebackup --host=localhost --pgdata=/var/lib/postgresql/restore \
    --format=tar --wal-method=stream

# Restore to specific timestamp
pg_ctl -D /var/lib/postgresql/restore start \
    -o "recovery_target_time='2026-06-06 10:30:00'"
```

### Method 3: Barman (Enterprise Backup)

**Barman installation**:

```bash
sudo apt install barman
```

**Barman configuration** (`/etc/barman.conf`):

```ini
[soothe]
description = "Soothe PostgreSQL cluster"
conninfo = host=localhost user=postgres dbname=soothe_checkpoints
backup_method = rsync
archiver = on
wal_retention_policy = main
retention_policy = RECOVERY WINDOW OF 4 WEEKS
```

**Barman backup commands**:

```bash
# Full backup
barman backup soothe

# List backups
barman list-backup soothe

# Restore backup
barman recover soothe latest /var/lib/postgresql/restore
```

## Configuration Backup

### Config File Backup

```bash
#!/bin/bash
# backup-config.sh - Configuration backup

CONFIG_DIR="/var/lib/soothe/config"
BACKUP_DIR="/var/backups/soothe/config"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p ${BACKUP_DIR}

# Backup config.yml
cp ${CONFIG_DIR}/config.yml ${BACKUP_DIR}/config_${DATE}.yml

# Backup .env (if exists)
if [ -f "/var/lib/soothe/.env" ]; then
    cp /var/lib/soothe/.env ${BACKUP_DIR}/env_${DATE}
fi

# Backup secrets from environment (optional)
# WARNING: Store securely with encryption
env | grep -E "(API_KEY|PASSWORD)" > ${BACKUP_DIR}/secrets_${DATE}

# Encrypt secrets
gpg --batch --yes --passphrase "${GPG_PASSPHRASE}" \
    --symmetric --cipher-algo AES256 \
    ${BACKUP_DIR}/secrets_${DATE}

# Upload to S3
aws s3 sync ${BACKUP_DIR}/ s3://soothe-backups/config/
```

### Secrets Manager Backup

**AWS Secrets Manager**:

```bash
# Backup secrets
aws secretsmanager get-secret-value \
    --secret-id soothe/dashscope-api-key \
    --query SecretString \
    --output text > dashscope_api_key_backup.txt

# Encrypt backup
gpg --symmetric --cipher-algo AES256 dashscope_api_key_backup.txt
```

**HashiCorp Vault**:

```bash
# Backup Vault secrets
vault kv get -format=json secret/soothe > soothe_secrets_backup.json

# Encrypt backup
gpg --symmetric soothe_secrets_backup.json
```

## Docker Volume Backup

### Volume Backup Script

```bash
#!/bin/bash
# backup-docker-volumes.sh

BACKUP_DIR="/var/backups/soothe/volumes"
DATE=$(date +%Y%m%d)

mkdir -p ${BACKUP_DIR}

# Backup PostgreSQL volume
docker run --rm \
    -v soothe_postgres_data:/source:ro \
    -v ${BACKUP_DIR}:/backup \
    alpine tar czf /backup/postgres_data_${DATE}.tar.gz -C /source .

# Backup daemon volume
docker run --rm \
    -v soothe_daemon_data:/source:ro \
    -v ${BACKUP_DIR}:/backup \
    alpine tar czf /backup/daemon_data_${DATE}.tar.gz -C /source .

# Upload to S3
aws s3 sync ${BACKUP_DIR}/ s3://soothe-backups/volumes/
```

### Volume Restore

```bash
#!/bin/bash
# restore-docker-volumes.sh

BACKUP_DATE="20260606"
BACKUP_DIR="/var/backups/soothe/volumes"

# Stop services
docker compose down

# Restore PostgreSQL volume
docker run --rm \
    -v soothe_postgres_data:/target \
    -v ${BACKUP_DIR}:/backup \
    alpine sh -c "cd /target && tar xzf /backup/postgres_data_${BACKUP_DATE}.tar.gz"

# Restore daemon volume
docker run --rm \
    -v soothe_daemon_data:/target \
    -v ${BACKUP_DIR}:/backup \
    alpine sh -c "cd /target && tar xzf /backup/daemon_data_${BACKUP_DATE}.tar.gz"

# Start services
docker compose up -d
```

## Disaster Recovery

### Recovery Scenarios

| Scenario | Recovery Method | RTO | RPO |
|----------|----------------|-----|-----|
| Database corruption | pg_dump restore | 1 hour | 24 hours |
| Hardware failure | Volume restore | 2 hours | 24 hours |
| Region outage | Remote backup restore | 4 hours | 24 hours |
| Point-in-time recovery | WAL streaming | 30 minutes | 0-1 hour |

**RTO**: Recovery Time Objective (time to restore)
**RPO**: Recovery Point Objective (data loss tolerance)

### Recovery Procedure

#### Full Database Recovery

```bash
#!/bin/bash
# restore-full.sh - Full database restore

BACKUP_DATE="20260606"
BACKUP_FILE="/var/backups/soothe/soothe_backup_${BACKUP_DATE}.tar.gz"
RESTORE_DIR="/tmp/soothe_restore"

# Stop daemon
docker compose stop soothed
# Or systemd: sudo systemctl stop soothed

# Extract backup
mkdir -p ${RESTORE_DIR}
tar xzf ${BACKUP_FILE} -C ${RESTORE_DIR}

# Drop existing databases (WARNING: destructive)
psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS soothe_checkpoints;"
psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS soothe_metadata;"
psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS soothe_vectors;"
psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS soothe_memory;"

# Restore databases
for db in soothe_checkpoints soothe_metadata soothe_vectors soothe_memory; do
    # Create database
    psql -h localhost -U postgres -c "CREATE DATABASE ${db};"
    
    # Restore data
    pg_restore -h localhost -U postgres -d ${db} \
        --format=custom \
        ${RESTORE_DIR}/${db}.dump
done

# Restore config
cp ${RESTORE_DIR}/config.yml /var/lib/soothe/config/config.yml
cp ${RESTORE_DIR}/.env /var/lib/soothe/.env

# Start daemon
docker compose start soothed
# Or systemd: sudo systemctl start soothed

# Verify restore
psql -h localhost -U postgres -d soothe_metadata \
    -c "SELECT count(*) FROM threads;"
```

#### Point-in-Time Recovery (PITR)

```bash
#!/bin/bash
# restore-pitr.sh - Point-in-time recovery

TARGET_TIME="2026-06-06 10:30:00"
WAL_DIR="/var/backups/soothe/wal"
RESTORE_DIR="/var/lib/postgresql/restore"

# Stop PostgreSQL
docker compose stop soothe-pgvector

# Create restore directory
mkdir -p ${RESTORE_DIR}

# Restore base backup
pg_basebackup --host=localhost --pgdata=${RESTORE_DIR} \
    --format=tar --wal-method=none

# Configure recovery
cat > ${RESTORE_DIR}/recovery.conf <<EOF
restore_command = 'aws s3 cp s3://soothe-backups/wal/%f %p'
recovery_target_time = '${TARGET_TIME}'
recovery_target_action = 'promote'
EOF

# Start PostgreSQL in recovery mode
pg_ctl -D ${RESTORE_DIR} start

# Wait for recovery completion
until pg_isready -h localhost; do
    sleep 5
done

# Verify recovery
psql -h localhost -U postgres -d soothe_metadata \
    -c "SELECT count(*) FROM threads WHERE created_at <= '${TARGET_TIME}';"
```

### Disaster Recovery Site

**Remote backup location** (different region):

```yaml
# S3 cross-region replication
aws s3api put-bucket-replication \
    --bucket soothe-backups-primary \
    --replication-configuration file://replication.json

# replication.json
{
  "Role": "arn:aws:iam::123456789:role/replication-role",
  "Rules": [{
    "Status": "Enabled",
    "Destination": {
      "Bucket": "arn:aws:s3:::soothe-backups-secondary"
    }
  }]
}
```

**Disaster recovery checklist**:

1. Verify backup integrity
2. Restore databases in DR site
3. Restore configuration files
4. Start daemon with DR config
5. Verify thread continuity
6. Update DNS/load balancer to DR site
7. Monitor for issues

## Backup Monitoring

### Backup Verification

```bash
#!/bin/bash
# verify-backup.sh - Backup integrity check

BACKUP_DATE=$(date +%Y%m%d)
BACKUP_FILE="/var/backups/soothe/soothe_backup_${BACKUP_DATE}.tar.gz"

# Verify backup exists
if [ ! -f ${BACKUP_FILE} ]; then
    echo "ERROR: Backup file missing: ${BACKUP_FILE}"
    exit 1
fi

# Verify backup integrity
tar tzf ${BACKUP_FILE} | grep -E "(\.dump|\.yml|\.env)" || {
    echo "ERROR: Backup file corrupted"
    exit 1
}

# Verify PostgreSQL dumps
for db in soothe_checkpoints soothe_metadata soothe_vectors soothe_memory; do
    pg_restore --list ${RESTORE_DIR}/${db}.dump | grep "TABLE DATA" || {
        echo "WARNING: ${db} dump may be incomplete"
    }
done

# Verify S3 upload
aws s3 ls s3://soothe-backups/${BACKUP_DATE}/ | grep "soothe_backup" || {
    echo "ERROR: Backup not uploaded to S3"
    exit 1
}

echo "Backup verification successful"
```

### Backup Alerts

**Backup failure alerting** (cron + email):

```bash
# /etc/cron.d/soothe-backup
0 2 * * * root /usr/local/bin/backup-postgres.sh || \
    mail -s "Soothe Backup Failed" admin@your-domain.com
```

**Backup monitoring dashboard** (Grafana):

```yaml
# Grafana alert rule
alert: backup_missing
expr: backup_last_success_timestamp < now() - 86400
severity: critical
annotations:
  summary: "No backup in last 24 hours"
```

## Backup Automation

### Cron Jobs

**`/etc/cron.d/soothe-backups`**:

```cron
# Weekly full backup (Sunday 2 AM)
0 2 * * 0 root /usr/local/bin/backup-postgres.sh

# Daily incremental backup (2 AM)
0 2 * * * root /usr/local/bin/backup-incremental.sh

# Config backup (on change, manual trigger)
# Run manually: sudo /usr/local/bin/backup-config.sh

# Backup verification (daily 3 AM)
0 3 * * * root /usr/local/bin/verify-backup.sh
```

### systemd Timer (Alternative to Cron)

**`/etc/systemd/system/soothe-backup.timer`**:

```ini
[Unit]
Description=Soothe Backup Timer

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
```

**`/etc/systemd/system/soothe-backup.service`**:

```ini
[Unit]
Description=Soothe Weekly Backup

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup-postgres.sh
```

**Enable timer**:

```bash
sudo systemctl enable soothe-backup.timer
sudo systemctl start soothe-backup.timer
```

## Backup Best Practices

### Security

1. **Encrypt backups**: Use GPG or AES-256 encryption
2. **Secure storage**: Use encrypted S3 buckets or private storage
3. **Access control**: Restrict backup file access (chmod 600)
4. **Rotate keys**: Periodically rotate encryption keys
5. **Test restores**: Monthly restore tests to verify integrity

### Testing

**Monthly restore test**:

```bash
#!/bin/bash
# test-restore.sh - Monthly restore verification

RESTORE_TEST_DIR="/tmp/restore_test"
BACKUP_DATE=$(date -d "7 days ago" +%Y%m%d)

# Create isolated restore environment
mkdir -p ${RESTORE_TEST_DIR}
docker run -d --name restore-test-postgres \
    -e POSTGRES_PASSWORD=test \
    -v ${RESTORE_TEST_DIR}:/restore \
    pgvector:pg17

# Restore backup to test container
docker exec restore-test-postgres \
    pg_restore -d soothe_checkpoints \
    /restore/soothe_checkpoints.dump

# Verify restore
docker exec restore-test-postgres \
    psql -U postgres -d soothe_checkpoints \
    -c "SELECT count(*) FROM checkpoints;"

# Cleanup
docker stop restore-test-postgres
docker rm restore-test-postgres
rm -rf ${RESTORE_TEST_DIR}

echo "Restore test successful"
```

### Compliance

**GDPR compliance**:
- Backup retention: 4 weeks (personal data)
- Encryption: AES-256 required
- Access logging: Track backup access
- Right to deletion: Must be able to delete threads from backups

**SOC 2 compliance**:
- Backup monitoring: Automated alerts
- Restore testing: Quarterly verification
- Encryption: At rest and in transit
- Access control: Role-based backup access

## Related Documentation

- [Production Setup](production-setup.md) - Deployment steps
- [Monitoring Guide](monitoring.md) - Backup monitoring
- [Scaling Strategies](scaling.md) - Multi-node backup strategies
- [Security Hardening](security.md) - Backup encryption

---

**Backup issues?** See [Troubleshooting](../troubleshooting.md) or contact admin team.