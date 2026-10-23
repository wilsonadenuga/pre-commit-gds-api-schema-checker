# Rules

The 11 rules the checker runs on an OpenAPI spec.

- **GDS** rules come from the [GDS API Technical and Data Standards](https://www.gov.uk/guidance/gds-api-technical-and-data-standards).
- **NCSC** rules come from the NCSC's [Securing HTTP-based APIs](https://www.ncsc.gov.uk/collection/securing-http-based-apis).
- **REC** rules are recommendations or our own standards, not GDS or NCSC requirements.

| Rule | Checks | Severity | Source |
|---|---|---|---|
| GDS-001 | Server URLs use `https://` | error | [GDS: Secure your API](https://www.gov.uk/guidance/gds-api-technical-and-data-standards) |
| GDS-002 | Date and time fields use ISO 8601 | warning | [GDS: Use ISO 8601 for dates and times](https://www.gov.uk/guidance/gds-api-technical-and-data-standards) |
| GDS-003 | The version is in the URL, e.g. `/v1` | warning | [GDS: Version your API](https://www.gov.uk/guidance/gds-api-technical-and-data-standards) |
| GDS-004 | Responses are JSON | warning | [GDS: Use JSON for response formats](https://www.gov.uk/guidance/gds-api-technical-and-data-standards) |
| GDS-005 | Errors use one standard shape and real HTTP codes | warning | [GDS: Use standard HTTP responses](https://www.gov.uk/guidance/gds-api-technical-and-data-standards) |
| NCSC-001 | No weak login methods (basic auth, plain API keys) | error | [NCSC §2: Avoid weak authentication methods](https://www.ncsc.gov.uk/collection/securing-http-based-apis/2-api-authentication-and-authorisation) |
| NCSC-002 | Every endpoint requires login | error | [NCSC §2: API authorisation](https://www.ncsc.gov.uk/collection/securing-http-based-apis/2-api-authentication-and-authorisation) |
| NCSC-003 | Request bodies reject unexpected fields | warning | [NCSC §4: Schema validation](https://www.ncsc.gov.uk/collection/securing-http-based-apis/4-input-validation) |
| NCSC-004 | Every endpoint documents a `429 Too Many Requests` | suggestion | [NCSC §5: DoS attack mitigation](https://www.ncsc.gov.uk/collection/securing-http-based-apis/5-dos-attack-mitigation) |
| REC-001 | Paths are lowercase-with-hyphens, plural, no verbs | suggestion | [Microsoft REST API Guidelines](https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md) |
| REC-002 | Every operation has a meaningful description (summary optional) | suggestion | Our standard, using [OpenAPI 3.1: Operation Object](https://spec.openapis.org/oas/v3.1.0.html#operation-object) |

## What good looks like

### GDS-001 — Server URLs use `https://`

```yaml
servers:
  - url: https://api.example.gov.uk/v1
```

### GDS-002 — Date and time fields use ISO 8601

```yaml
properties:
  createdAt:
    type: string
    format: date-time
  dateOfBirth:
    type: string
    format: date
```

### GDS-003 — The version is in the URL

```yaml
paths:
  /v1/users:
    get: {...}
```

### GDS-004 — Responses are JSON

```yaml
responses:
  '200':
    description: OK
    content:
      application/json:
        schema:
          $ref: '#/components/schemas/User'
```

### GDS-005 — Errors use one standard shape

Errors use RFC 9457 problem details (`application/problem+json`) on a real HTTP code.

```yaml
responses:
  '500':
    description: Server error
    content:
      application/problem+json:
        schema:
          $ref: '#/components/schemas/Problem'
```

### NCSC-001 — No weak login methods

Use OAuth 2.0 or OpenID Connect instead of basic auth or plain API keys.

```yaml
components:
  securitySchemes:
    departmentOAuth:
      type: oauth2
      flows:
        clientCredentials:
          tokenUrl: https://auth.example.gov.uk/token
          scopes: {}
```

### NCSC-002 — Every endpoint requires login

Set login once for the whole API, and don't switch it off with `security: []`.

```yaml
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get: {...}
```

### NCSC-003 — Request bodies reject unexpected fields

```yaml
requestBody:
  content:
    application/json:
      schema:
        type: object
        additionalProperties: false
        properties:
          name: {type: string}
```

### NCSC-004 — Every endpoint documents a `429`

```yaml
responses:
  '200': {...}
  '429':
    description: Too Many Requests
    content:
      application/problem+json:
        schema:
          $ref: '#/components/schemas/Problem'
```

### REC-001 — Paths are lowercase-with-hyphens and plural (recommendation)

```yaml
paths:
  /v1/users:
    get: {...}
  /v1/user-preferences:
    get: {...}
```

### REC-002 — Every operation has a meaningful description (our standard)

AI agents read the description to decide which operation to call, so it must be
there and must not be a placeholder. The summary is optional. An AI review also
checks that every summary and description is clear, plain English and explains
what the operation does; it suggests rewrites you can accept or reject.

```yaml
paths:
  /v1/users:
    get:
      summary: List users
      description: Returns a list of users visible to the caller.
```
