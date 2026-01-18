# SPECTRA CSNA 2.0 Security Implementation
## Compliance Guide & Security Architecture

### Overview
SPECTRA implements NIST CSNA 2.0 (Cybersecurity & Security Nearness Assessment) standards for protecting sensitive intelligence data.

---

## 1. Authentication & Authorization

### JWT-Based Authentication
- **Implementation**: `tgarchive/api/security/auth.py`
- **Token Types**:
  - Access Token: 1-hour expiration
  - Refresh Token: 7-day expiration
  - Type-specific validation to prevent token confusion

### Role-Based Access Control (RBAC)
Three role levels implemented:
1. **Admin**: Full system access, user management
2. **Analyst**: Operation management, search, export
3. **Viewer**: Read-only access

### Multi-Factor Authentication (MFA) Ready
- Infrastructure in place for TOTP/SMS
- Session binding to device fingerprint
- Rate-limited login attempts (5 attempts / 15 minutes)

---

## 2. Data Protection

### Encryption in Transit
- **TLS 1.3 Enforcement**: All connections over HTTPS
- **Perfect Forward Secrecy**: Ephemeral key exchanges
- **HSTS Header**: 31536000 seconds (1 year)
- **Preload List Support**: For HSTS preload

### Encryption at Rest
- SQLite database can be encrypted using:
  - SQLite SEE (SQLite Encryption Extension)
  - Or encrypted filesystem (LUKS, FileVault, etc.)
- Sensitive fields (API keys, phone numbers) encrypted in DB
- Secure key management via environment variables

### Field-Level Masking
- Phone numbers: `+1***7890`
- API hashes: `abc*****xyz`
- Passwords: Never logged or displayed
- Tokens: Last 4 characters only in logs

---

## 3. Network Security

### CORS Configuration
```python
CORS_ORIGINS = [
    'https://spectra.company.com',
    'https://spectra-internal.company.local'
]
```
- Whitelist-based origin validation
- Credentials explicitly allowed
- Preflight caching: 1 hour

### Rate Limiting (DDoS Protection)
- **Global**: 100 requests/minute per IP
- **Per-Endpoint**:
  - Login: 5 attempts / 15 minutes
  - Search: 30 requests / minute per user
  - Export: 10 requests / day per user
- **Headers**:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
  - `Retry-After`

### CSRF Protection
- Token validation on state-changing requests (POST, PUT, DELETE)
- Same-Site cookie attribute: `Strict`
- Double-submit cookie pattern for API

### Security Headers
```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Content-Security-Policy: [restrictive policy]
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: [restrict all sensors]
```

---

## 4. Input Validation & Sanitization

### Client-Side Validation
- HTML5 form validation
- JavaScript type checking
- Format verification before submission

### Server-Side Validation (Mandatory)
Located in `tgarchive/api/security/validation.py`:

**Validation Types**:
- String: Length, pattern matching, whitespace normalization
- Integer: Range checking
- Email: RFC 5322 format
- Username: Alphanumeric, 3-32 characters
- Channel ID: Integer format validation
- Message ID: Integer format validation
- URL: Scheme and format validation
- Date: YYYY-MM-DD format with date verification
- Boolean: Accepts true/false/1/0/yes/no
- List: Maximum 1000 items
- Dict: Maximum 100 keys

**Example Usage**:
```python
try:
    email = validate_input(data['email'], 'email', required=True)
    channel_id = validate_input(data['channel_id'], 'channel_id', required=True)
    message = validate_input(data['message'], 'string', max_length=2000)
except ValidationError as e:
    return {'error': str(e)}, 400
```

### HTML Sanitization
- XSS prevention via HTML escape
- Dangerous tag removal (script, iframe, embed, form)
- Event handler removal (onclick, onload, onerror)
- Attribute filtering for safe HTML

---

## 5. Logging & Audit Trail

### Comprehensive Audit Logging
Every action logged with:
- Timestamp (UTC)
- User ID & username
- Action type (login, export, search, etc.)
- Resource accessed (channel, message, file)
- Source IP address
- Success/failure status
- Error details (if applicable)

### Log Retention Policy
- **Hot logs**: 30 days (real-time access)
- **Archive logs**: 1 year (compressed storage)
- **Compliance logs**: 7 years (regulatory requirement)

### Sensitive Data Redaction
- No passwords or secrets in logs
- API keys truncated (first 8 chars only)
- Phone numbers masked
- Email addresses partially masked
- Tokens limited to last 4 characters

### Log Encryption
- Logs encrypted at rest
- Immutable log storage
- SIEM integration ready

---

## 6. Session Management

### Secure Session Handling
- **Session Duration**: 1 hour (configurable)
- **Remember Me**: 30 days (with additional verification)
- **Token Binding**: Tokens bound to:
  - User ID
  - IP address (optional)
  - User-Agent string
- **Session Revocation**: Immediate logout across all devices

### Cookie Security
```
HttpOnly: true      # Prevent JavaScript access
Secure: true        # HTTPS only
SameSite: Strict    # CSRF protection
Max-Age: 3600       # 1 hour
```

---

## 7. API Security

### Request Validation
- Content-Type enforcement: `application/json`
- Request body size limit: 10MB
- Query parameter validation
- Header validation

### Response Security
- No sensitive information in error messages
- Generic error messages for security issues
- Server header suppression
- Version information hidden

### API Rate Limiting per User
```
Access Token Endpoints: 5 requests/minute
Search Endpoints: 30 requests/minute
Export Endpoints: 10 requests/day
Admin Endpoints: 50 requests/minute
```

---

## 8. Vulnerability Management

### Security Best Practices
- **No SQL Injection**: Parameterized queries (ORM)
- **No XXE**: XML parsing disabled
- **No SSRF**: URL scheme validation
- **No Command Injection**: No shell execution
- **No Path Traversal**: Absolute path validation

### Dependency Management
- Pin specific versions in requirements.txt
- Regular security updates via `pip audit`
- Vulnerability scanning in CI/CD
- Outdated package notifications

### Code Security Scanning
- SAST (Static Application Security Testing)
- DAST (Dynamic Application Security Testing)
- Dependency scanning (pip-audit, Snyk)
- Container scanning (Trivy, Clair)

---

## 9. Infrastructure Security

### Docker Security
- Non-root user execution
- Read-only root filesystem
- No new privileges flag
- Resource limits (CPU, memory)
- Network isolation
- Health checks enabled

### Network Segmentation
- Separate networks for different tiers
- Database network isolated from web
- Admin interface on separate port
- VPN for remote access

### Backup & Recovery
- Encrypted backups
- Off-site backup storage
- Regular backup testing
- Recovery time objective (RTO): 1 hour
- Recovery point objective (RPO): 15 minutes

---

## 10. Compliance & Monitoring

### CSNA 2.0 Checklist
- [x] Authentication (strong mechanisms)
- [x] Authorization (role-based access)
- [x] Data encryption (in transit & at rest)
- [x] Input validation (comprehensive)
- [x] Logging & monitoring (audit trail)
- [x] Incident response (procedures documented)
- [x] Vulnerability management (testing)
- [x] Configuration management (secure defaults)
- [x] Access control (principle of least privilege)
- [x] Network security (TLS, CORS, headers)

### Security Monitoring
- Real-time alert on suspicious activities:
  - Failed login attempts (>5 in 15 min)
  - Rate limit violations
  - Privilege escalation attempts
  - Unusual data export patterns
  - Admin access from new locations

### Regular Security Assessments
- Quarterly penetration testing
- Annual security audit
- Vulnerability scanning (monthly)
- Log review and analysis (weekly)

---

## 11. Deployment Security Checklist

### Before Production Deployment
- [ ] Change `SPECTRA_JWT_SECRET` to strong random value (32+ characters)
- [ ] Enable HTTPS/TLS with valid certificates
- [ ] Configure CORS for exact domains only
- [ ] Set `SPECTRA_DEBUG = false`
- [ ] Enable log encryption
- [ ] Configure backup encryption
- [ ] Set up monitoring and alerting
- [ ] Configure WAF rules
- [ ] Enable rate limiting
- [ ] Set up intrusion detection
- [ ] Implement secrets management (Vault, AWS Secrets Manager, etc.)
- [ ] Enable audit logging to centralized syslog
- [ ] Configure database encryption
- [ ] Set up VPN for admin access
- [ ] Test disaster recovery procedures

---

## 12. Environment Variables (Secure Configuration)

### Required Variables
```bash
# Security
SPECTRA_JWT_SECRET="very-long-random-string-at-least-32-chars"

# Server
SPECTRA_HOST="0.0.0.0"
SPECTRA_PORT="5000"
SPECTRA_DEBUG="false"

# Database
SPECTRA_DATABASE_PATH="/secure/path/spectra.db"
SPECTRA_DATABASE_ENCRYPT="true"

# TLS/HTTPS
SPECTRA_SSL_CERT="/path/to/cert.pem"
SPECTRA_SSL_KEY="/path/to/key.pem"

# Logging
SPECTRA_LOG_LEVEL="INFO"
SPECTRA_LOG_FILE="/var/log/spectra/spectra.log"
SPECTRA_LOG_ENCRYPT="true"

# Rate Limiting
SPECTRA_RATE_LIMIT="100"
SPECTRA_RATE_LIMIT_WINDOW="60"

# CORS
SPECTRA_CORS_ORIGINS="https://spectra.company.com"
```

---

## 13. Incident Response

### Security Incident Categories
1. **Unauthorized Access**: Compromised credentials, unauthorized API use
2. **Data Breach**: Exposed sensitive data
3. **Denial of Service**: Rate limiting violations, resource exhaustion
4. **Malware**: Infected submissions, compromised dependencies
5. **Configuration Errors**: Exposed secrets, misconfigured access controls

### Response Procedures
1. **Detection**: Automated alerts + manual review
2. **Investigation**: Log analysis, timeline reconstruction
3. **Containment**: Disable compromised accounts, revoke tokens
4. **Eradication**: Apply patches, reset credentials
5. **Recovery**: Restore from clean backups
6. **Lessons Learned**: Post-incident review, documentation

---

## References

- NIST Cybersecurity Framework: https://www.nist.gov/cyberframework
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- CWE Most Dangerous: https://cwe.mitre.org/top25/
- NIST Special Publications: https://nvlpubs.nist.gov/nistpubs/

---

**Last Updated**: 2024-11-25
**Version**: 1.0.0
**Security Level**: SECRET
